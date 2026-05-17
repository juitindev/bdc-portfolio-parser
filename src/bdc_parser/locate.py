"""Locate Schedule of Investments table(s) in a 10-K HTML document.

The Schedule typically spans multiple <table> elements (page breaks in the
original filing). We identify them by header-row text and by adjacency
to other investment-data tables.

Most BDC 10-Ks report the current fiscal year's Schedule first, followed by
the prior-year comparative. find_schedule_groups() returns groups in
document order; the caller usually wants groups[0] (current FY).
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from bdc_parser.models import BDCProfile
from bdc_parser.paths import cache_path

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SECTION_MARKERS = [
    "Control Investments",
    "Affiliate Investments",
    "Non-control/Non-affiliate Investments",
]

TOTAL_PATTERNS = [
    r"Total Control Investments",
    r"Total Affiliate Investments",
    r"Total Non-control",
    r"Total Investments\b",
    r"Total Investments and Money Market",
]


@dataclass
class ScheduleGroup:
    """One contiguous run of <table> elements that together form a Schedule of Investments."""
    header_table: int           # index of the table that contains the column-header row
    tables: list[int] = field(default_factory=list)  # all table indices in this group, in order

    @property
    def start(self) -> int:
        return self.tables[0]

    @property
    def end(self) -> int:
        return self.tables[-1]


def is_header_table(table) -> bool:
    """Check if this table starts with the Schedule header rows.

    BDCs commonly split the Schedule header across two <tr> rows:
      Row 1: Portfolio Company | Variable Index | Rate | ...
      Row 2: Investment Type   | Industry       | Spread / Floor | ...
    So we check the combined text of the first 5 rows.
    """
    rows = table.find_all("tr", limit=5)
    combined = " ".join(row.get_text(strip=True).lower() for row in rows)
    return "portfolio company" in combined and "investment type" in combined


def has_investment_data(table) -> bool:
    """Check if this table contains investment-style rows (company + rate + amounts)."""
    rows = table.find_all("tr")
    investment_rows = 0
    for row in rows:
        cells = row.find_all(["td", "th"])
        texts = [c.get_text(strip=True) for c in cells]
        joined = " ".join(texts)
        has_date = bool(re.search(r"\d{1,2}/\d{1,2}/\d{4}", joined))
        has_rate = bool(re.search(r"\d+\.\d+%", joined))
        has_lien = bool(re.search(r"(First|Second) Lien|Subordinated|Equity|Warrant", joined))
        if has_date and (has_rate or has_lien):
            investment_rows += 1
    return investment_rows >= 3


def find_schedule_groups(html: str) -> list[ScheduleGroup]:
    """Detect Schedule of Investments table groups in a 10-K HTML document.

    Returns groups in document order. Each group is a header table plus the
    continuation tables (up to 2 positions away) that contain investment data.
    """
    soup = BeautifulSoup(html, "lxml")
    all_tables = soup.find_all("table")

    groups: list[ScheduleGroup] = []
    current: ScheduleGroup | None = None

    for i, table in enumerate(all_tables):
        if is_header_table(table):
            if current is not None:
                groups.append(current)
            current = ScheduleGroup(header_table=i, tables=[i])
        elif current is not None and has_investment_data(table):
            if i - current.tables[-1] <= 2:
                current.tables.append(i)

    if current is not None:
        groups.append(current)

    return groups


def find_sections_in_table(table) -> list[str]:
    """Find section markers within a table."""
    found = []
    for row in table.find_all("tr"):
        text = row.get_text(strip=True)
        for marker in SECTION_MARKERS:
            if marker.lower() in text.lower() and "total" not in text.lower():
                found.append(marker)
    return found


def find_totals_in_table(table) -> list[str]:
    """Find total/subtotal rows."""
    found = []
    for row in table.find_all("tr"):
        text = row.get_text(strip=True)
        for pattern in TOTAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                amounts = re.findall(r"[\d,]+", text)
                amt_str = amounts[-1] if amounts else "?"
                found.append(f"{text[:60].strip()} → ${amt_str}")
                break
    return found


def get_sample_data_rows(table, n=3) -> list[list[str]]:
    """Get sample data rows that look like actual investment entries."""
    samples = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        texts = [c.get_text(strip=True) for c in cells]
        non_empty = [t for t in texts if t]

        if len(non_empty) < 3:
            continue
        joined = " ".join(non_empty).lower()
        if "portfolio company" in joined and "investment type" in joined:
            continue
        if any(m.lower() in joined for m in SECTION_MARKERS) and len(non_empty) < 5:
            continue

        samples.append([t[:55] for t in non_empty])
        if len(samples) >= n:
            break
    return samples


def spot_bdc_quirks(table) -> list[str]:
    """Flag BDC-specific data patterns."""
    text = table.get_text()
    quirks = []
    if re.search(r"PIK", text):
        quirks.append("PIK interest")
    if re.search(r"non-accrual", text, re.IGNORECASE):
        quirks.append("Non-accrual")
    if re.search(r"\([a-z]{1,2}\)", text):
        quirks.append("Footnote markers")
    if re.search(r"unfunded commitment", text, re.IGNORECASE):
        quirks.append("Unfunded commitments")
    if re.search(r"Warrant", text):
        quirks.append("Warrants")
    return quirks


def run(profile: BDCProfile):
    """Locate Schedule of Investments tables and print a diagnostic summary."""
    path = cache_path(profile.ticker)
    if not path.exists():
        print(f"ERROR: Cache file not found at {path}")
        print(f"Run `bdc-parse fetch {profile.ticker}` first.")
        return

    print(f"Loading HTML ({path.stat().st_size / 1024 / 1024:.1f} MB)...")
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    all_tables = soup.find_all("table")
    print(f"Total tables in document: {len(all_tables)}\n")

    groups = find_schedule_groups(html)
    print(f"Found {len(groups)} Schedule of Investments group(s)\n")
    print("=" * 80)

    for g_idx, group in enumerate(groups):
        print(f"\nSCHEDULE GROUP {g_idx + 1}")
        print(f"  Tables: #{group.start} through #{group.end}")
        print(f"  Spans {len(group.tables)} HTML table element(s)")

        total_rows = 0
        all_sections = []
        all_totals = []
        all_quirks = set()

        for t_idx in group.tables:
            table = all_tables[t_idx]
            rows = table.find_all("tr")
            total_rows += len(rows)
            all_sections.extend(find_sections_in_table(table))
            all_totals.extend(find_totals_in_table(table))
            all_quirks.update(spot_bdc_quirks(table))

        print(f"  Total rows across all tables: {total_rows}")

        if all_sections:
            print(f"\n  Sections found:")
            for s in all_sections:
                print(f"    - {s}")

        if all_totals:
            print(f"\n  Totals/subtotals:")
            for t in all_totals:
                print(f"    - {t}")

        if all_quirks:
            print(f"\n  BDC quirks: {', '.join(sorted(all_quirks))}")

        print(f"\n  Sample data rows per table:")
        for t_idx in group.tables:
            table = all_tables[t_idx]
            row_count = len(table.find_all("tr"))
            samples = get_sample_data_rows(table, n=2)
            sections = find_sections_in_table(table)
            sec_label = f" [{', '.join(sections)}]" if sections else ""
            print(f"\n    Table #{t_idx} ({row_count} rows){sec_label}:")
            for s in samples:
                print(f"      {s}")

        print("\n" + "=" * 80)
