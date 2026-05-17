"""Locate Schedule of Investments table(s) in the cached FDUS 10-K HTML.

The Schedule spans multiple <table> elements (page breaks in the original filing).
We identify them by the header row pattern and by section markers within the tables.

Migrated from src/locate_schedule.py — logic unchanged.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = PROJECT_ROOT / "raw" / "fdus_10k_latest.html"

# Section markers that appear as standalone row text
SECTION_MARKERS = [
    "Control Investments",
    "Affiliate Investments",
    "Non-control/Non-affiliate Investments",
]

# Totals patterns
TOTAL_PATTERNS = [
    r"Total Control Investments",
    r"Total Affiliate Investments",
    r"Total Non-control",
    r"Total Investments\b",
    r"Total Investments and Money Market",
]


def is_header_table(table) -> bool:
    """Check if this table starts with the Schedule header rows.

    FDUS splits the header across two rows:
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


def main():
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache file not found at {CACHE_PATH}")
        print("Run fetch_filing.py first.")
        return

    print(f"Loading HTML ({CACHE_PATH.stat().st_size / 1024 / 1024:.1f} MB)...")
    html = CACHE_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    all_tables = soup.find_all("table")
    print(f"Total tables in document: {len(all_tables)}\n")

    schedule_groups = []
    current_group = None

    for i, table in enumerate(all_tables):
        if is_header_table(table):
            if current_group:
                schedule_groups.append(current_group)
            current_group = {"start": i, "tables": [i], "header_table": i}
        elif current_group and has_investment_data(table):
            if i - current_group["tables"][-1] <= 2:
                current_group["tables"].append(i)

    if current_group:
        schedule_groups.append(current_group)

    print(f"Found {len(schedule_groups)} Schedule of Investments group(s)\n")
    print("=" * 80)

    for g_idx, group in enumerate(schedule_groups):
        print(f"\nSCHEDULE GROUP {g_idx + 1}")
        print(f"  Tables: #{group['tables'][0]} through #{group['tables'][-1]}")
        print(f"  Spans {len(group['tables'])} HTML table element(s)")

        total_rows = 0
        all_sections = []
        all_totals = []
        all_quirks = set()

        for t_idx in group["tables"]:
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
        for t_idx in group["tables"]:
            table = all_tables[t_idx]
            row_count = len(table.find_all("tr"))
            samples = get_sample_data_rows(table, n=2)
            sections = find_sections_in_table(table)
            sec_label = f" [{', '.join(sections)}]" if sections else ""
            print(f"\n    Table #{t_idx} ({row_count} rows){sec_label}:")
            for s in samples:
                print(f"      {s}")

        print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
