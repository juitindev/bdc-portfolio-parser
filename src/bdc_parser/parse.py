"""Parse the FY2025 Schedule of Investments (tables #79-#83) into a flat CSV.

Row classification strategy — each <tr> is one of:
  - HEADER:    contains "Portfolio Company" / "Investment Type"
  - SECTION:   single non-empty cell matching a section label
  - COMPANY:   exactly 2 non-empty cells: company name + industry
  - INVEST:    first cell contains investment-type keyword (Lien, Equity, etc.)
  - SUBTOTAL:  cell[0] empty, has numeric values (company-level subtotal)
  - TOTAL:     cell[0] starts with "Total"
  - EMPTY:     all cells blank

For INVEST rows, we extract fields by content-pattern matching rather than
hard-coded cell indices, because $ signs and ) occupy their own cells and
shift positions.

Table indices to parse are detected by bdc_parser.locate.find_schedule_groups()
— no hardcoded FY2025_TABLES list. We parse groups[0] (most recent FY).
"""
from __future__ import annotations

import re
import csv
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from bdc_parser.locate import find_schedule_groups

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = PROJECT_ROOT / "raw" / "fdus_10k_latest.html"
OUTPUT_PATH = PROJECT_ROOT / "data" / "fdus_schedule_full.csv"

SECTION_LABELS = [
    ("non-control/non-affiliate investments", "Non-control/Non-affiliate"),
    ("affiliate investments", "Affiliate"),
    ("control investments", "Control"),
]

INVEST_TYPE_PATTERNS = re.compile(
    r"(First Lien|Second Lien|Subordinated|Mezzanine|"
    r"Preferred Equity|Common Equity|Warrant|Revolving Loan)",
    re.IGNORECASE,
)

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
RATE_RE = re.compile(r"\d+\.\d+%\s*/\s*\d+\.\d+%")
SPREAD_RE = re.compile(r"\([SP]\+")
AMOUNT_RE = re.compile(r"^[\d,]+$")
NEG_OPEN_RE = re.compile(r"^\([\d,]+$")


def clean_amount(raw: str) -> str:
    """Clean a numeric string: strip $, commas. Handle (X) negatives."""
    if not raw or raw == "—" or raw == "—":
        return ""
    s = raw.replace("$", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return s


def strip_footnotes(name: str) -> str:
    """Remove trailing footnote markers like (a), (n), (am), (h)(j), etc."""
    cleaned = re.sub(r"\s*\((?:fka\s+[^)]+)\)", r"", name)
    cleaned = re.sub(r"\s*\([a-z]{1,3}\)", "", cleaned)
    dba_match = re.search(r"\(dba\s+[^)]+\)", name)
    if dba_match:
        if "dba" not in cleaned:
            cleaned = cleaned.strip() + " " + dba_match.group()
    return cleaned.strip()


def classify_row(cells_text: list[str]) -> str:
    """Classify a row based on its cell contents."""
    non_empty = [t for t in cells_text if t and t not in ("$", "%")]
    if not non_empty:
        return "EMPTY"

    first = cells_text[0].strip() if cells_text[0].strip() else ""
    joined_lower = " ".join(non_empty).lower()

    if "portfolio company" in joined_lower and "investment type" in joined_lower:
        return "HEADER"

    if first:
        first_lower = first.lower()
        for key, _ in SECTION_LABELS:
            if key in first_lower and "total" not in first_lower:
                return "SECTION"
        if first_lower.startswith("total"):
            return "TOTAL"

    if first and INVEST_TYPE_PATTERNS.search(first):
        return "INVEST"

    if first:
        numeric_cells = [t for t in non_empty if AMOUNT_RE.match(t.replace(",", "").replace("$", ""))]
        if len(numeric_cells) <= 1 and len(non_empty) <= 3:
            if len(non_empty) >= 2:
                second = non_empty[1]
                if not DATE_RE.match(second) and not RATE_RE.search(second) and not AMOUNT_RE.match(second):
                    return "COMPANY"
            elif len(non_empty) == 1 and not AMOUNT_RE.match(first.replace(",", "")):
                return "COMPANY"

    if not first:
        amounts = [t for t in non_empty if AMOUNT_RE.match(t) or NEG_OPEN_RE.match(t)]
        if amounts:
            return "SUBTOTAL"

    return "UNKNOWN"


def extract_investment_fields(cells_text: list[str]) -> dict:
    """Extract structured fields from an INVEST row by content pattern matching."""
    fields = {
        "investment_type": "",
        "rate_spread_floor": "",
        "rate_cash_pik": "",
        "investment_date": "",
        "maturity_date": "",
        "principal_amount": "",
        "cost": "",
        "fair_value": "",
    }

    raw_type = cells_text[0].strip()
    inv_type = re.sub(r"\s*\(\$[\d,]+\s*unfunded commitment\)", "", raw_type)
    inv_type = re.sub(r"\s*\([a-z]{1,3}\)", "", inv_type)
    inv_type = re.sub(r"\s*\([\d,.]+\s*(?:LP\s+)?(?:units?|shares?)\)", "", inv_type, flags=re.IGNORECASE)
    inv_type = re.sub(r"\s*\(Units?\s+N/A\)", "", inv_type, flags=re.IGNORECASE)
    fields["investment_type"] = inv_type.strip()

    dates_found = []
    amounts_found = []
    pending_negative = None

    for idx, cell in enumerate(cells_text[1:], start=1):
        text = cell.strip()
        if not text or text in ("$", "%"):
            continue

        if NEG_OPEN_RE.match(text):
            pending_negative = text
            continue
        if text == ")" and pending_negative is not None:
            merged = pending_negative + ")"
            amounts_found.append(clean_amount(merged))
            pending_negative = None
            continue
        if pending_negative is not None:
            amounts_found.append(clean_amount(pending_negative + ")"))
            pending_negative = None

        if SPREAD_RE.search(text):
            fields["rate_spread_floor"] = text
        elif RATE_RE.search(text):
            fields["rate_cash_pik"] = text
        elif DATE_RE.match(text):
            dates_found.append(text)
        elif AMOUNT_RE.match(text) or text in ("—", "—"):
            amounts_found.append(clean_amount(text))

    if len(dates_found) >= 1:
        fields["investment_date"] = dates_found[0]
    if len(dates_found) >= 2:
        fields["maturity_date"] = dates_found[1]

    is_debt = any(kw in fields["investment_type"].lower() for kw in
                  ["lien", "subordinated", "mezzanine", "revolving"])
    if is_debt:
        if len(amounts_found) >= 3:
            fields["principal_amount"] = amounts_found[0]
            fields["cost"] = amounts_found[1]
            fields["fair_value"] = amounts_found[2]
        elif len(amounts_found) == 2:
            fields["principal_amount"] = amounts_found[0]
            fields["cost"] = amounts_found[1]
        elif len(amounts_found) == 1:
            fields["principal_amount"] = amounts_found[0]
    else:
        if len(amounts_found) >= 2:
            fields["cost"] = amounts_found[0]
            fields["fair_value"] = amounts_found[1]
        elif len(amounts_found) == 1:
            fields["cost"] = amounts_found[0]

    return fields


def main():
    if not CACHE_PATH.exists():
        print("ERROR: Run fetch_filing.py first.")
        return

    print(f"Loading HTML...")
    html = CACHE_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    all_tables = soup.find_all("table")

    groups = find_schedule_groups(html)
    if not groups:
        print("ERROR: No Schedule of Investments tables detected.")
        return
    target = groups[0]  # current FY — earliest in document order
    print(f"Detected Schedule of Investments: tables #{target.start}-#{target.end} "
          f"({len(target.tables)} tables)")
    if len(groups) > 1:
        prior = groups[1]
        print(f"  (also found {len(groups) - 1} prior-period group(s), e.g. "
              f"tables #{prior.start}-#{prior.end} — not parsed)")

    current_section = "Unknown"
    current_company = ""
    current_industry = ""
    rows_out = []
    unknown_rows = []

    for t_idx in target.tables:
        table = all_tables[t_idx]
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(strip=True) for c in cells]

            row_type = classify_row(texts)

            if row_type == "SECTION":
                first_lower = texts[0].strip().lower()
                for key, label in SECTION_LABELS:
                    if key in first_lower:
                        current_section = label
                        break

            elif row_type == "COMPANY":
                non_empty = [t for t in texts if t and t not in ("$", "%")]
                current_company = strip_footnotes(non_empty[0])
                current_industry = non_empty[1] if len(non_empty) >= 2 else ""

            elif row_type == "INVEST":
                fields = extract_investment_fields(texts)
                rows_out.append({
                    "company_name": current_company,
                    "industry": current_industry,
                    "investment_category": current_section,
                    "investment_type": fields["investment_type"],
                    "rate_spread_floor": fields["rate_spread_floor"],
                    "rate_cash_pik": fields["rate_cash_pik"],
                    "investment_date": fields["investment_date"],
                    "maturity_date": fields["maturity_date"],
                    "principal_amount": fields["principal_amount"],
                    "cost": fields["cost"],
                    "fair_value": fields["fair_value"],
                })

            elif row_type == "UNKNOWN":
                non_empty = [t for t in texts if t]
                if len(non_empty) >= 2:
                    unknown_rows.append(non_empty[:5])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "company_name", "industry", "investment_category", "investment_type",
        "rate_spread_floor", "rate_cash_pik", "investment_date", "maturity_date",
        "principal_amount", "cost", "fair_value",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\nParsed {len(rows_out)} investment rows")
    print(f"Saved to {OUTPUT_PATH}\n")

    total_fv = 0
    missing_fv = 0
    for r in rows_out:
        if r["fair_value"]:
            try:
                total_fv += float(r["fair_value"])
            except ValueError:
                pass
        else:
            missing_fv += 1

    print(f"Total fair value: ${total_fv:,.0f}K")
    print(f"Expected:         $1,324,753K")
    diff = total_fv - 1324753
    print(f"Difference:       ${diff:+,.0f}K")
    if missing_fv:
        print(f"Rows with missing fair_value: {missing_fv}")

    print(f"\nBy investment category:")
    from collections import Counter
    cat_counts = Counter(r["investment_category"] for r in rows_out)
    for cat, count in cat_counts.most_common():
        cat_fv = sum(float(r["fair_value"]) for r in rows_out
                     if r["investment_category"] == cat and r["fair_value"])
        print(f"  {cat}: {count} rows, ${cat_fv:,.0f}K fair value")

    print(f"\nBy investment type:")
    type_counts = Counter(r["investment_type"] for r in rows_out)
    for typ, count in type_counts.most_common():
        print(f"  {typ}: {count}")

    print(f"\nFirst 10 rows:")
    print(f"{'Company':<40} {'Type':<20} {'Cost':>10} {'FV':>10}")
    print("-" * 84)
    for r in rows_out[:10]:
        print(f"{r['company_name'][:39]:<40} {r['investment_type'][:19]:<20} "
              f"{r['cost']:>10} {r['fair_value']:>10}")

    if unknown_rows:
        print(f"\n{len(unknown_rows)} UNKNOWN rows (may need investigation):")
        for u in unknown_rows[:10]:
            print(f"  {u}")


if __name__ == "__main__":
    main()
