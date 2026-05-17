"""Extract all filing data for InductiveHealth Informatics from the Schedule CSV + raw 10-K HTML.

Migrated from src/extract_company_filing_data.py — logic unchanged.
"""
from __future__ import annotations

import csv
import json
import re
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = PROJECT_ROOT / "data" / "fdus_schedule_full.csv"
HTML_PATH = PROJECT_ROOT / "raw" / "fdus_10k_latest.html"
OUTPUT_PATH = PROJECT_ROOT / "data" / "inductivehealth_filing_data.json"

TARGET = "inductivehealth"


def find_schedule_rows() -> list[dict]:
    """Filter CSV rows matching the target company."""
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    matches = [r for r in rows if TARGET in r["company_name"].lower()]
    print(f"Found {len(matches)} schedule rows for target")

    cleaned = []
    for r in matches:
        cleaned.append({k: (v if v else None) for k, v in r.items()})
    return cleaned


def find_other_mentions(schedule_company_name: str) -> list[dict]:
    """Search the full 10-K HTML for mentions of InductiveHealth outside the Schedule tables.

    Returns context snippets with ±200 chars around each match.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    full_text = soup.get_text(separator=" ")
    full_text = re.sub(r"\s+", " ", full_text)

    pattern = re.compile(r"InductiveHealth", re.IGNORECASE)
    matches = list(pattern.finditer(full_text))
    print(f"Total mentions of 'InductiveHealth' in full text: {len(matches)}")

    snippets = []
    seen_contexts = set()

    for m in matches:
        start = max(0, m.start() - 200)
        end = min(len(full_text), m.end() + 200)
        snippet = full_text[start:end].strip()

        key = snippet[:80]
        if key in seen_contexts:
            continue
        seen_contexts.add(key)

        broad_start = max(0, m.start() - 500)
        broad = full_text[broad_start:m.start()].lower()

        section = "unknown"
        if "schedule of investments" in broad or "portfolio company" in broad:
            section = "schedule_of_investments"
        elif "fair value" in broad and ("level" in broad or "hierarchy" in broad):
            section = "fair_value_measurements"
        elif "unfunded" in broad or "commitment" in broad:
            section = "commitments"
        elif "realized" in broad or "unrealized" in broad:
            section = "gains_losses"
        elif "affiliate" in broad or "control" in broad:
            section = "affiliate_transactions"
        elif "risk" in broad:
            section = "risk_factors"
        elif "management" in broad and "discussion" in broad:
            section = "md_and_a"

        snippets.append({
            "position": m.start(),
            "likely_section": section,
            "snippet": snippet,
        })

    non_schedule = [s for s in snippets if s["likely_section"] != "schedule_of_investments"]
    schedule_only = [s for s in snippets if s["likely_section"] == "schedule_of_investments"]

    print(f"  In Schedule of Investments: {len(schedule_only)} mentions (already captured)")
    print(f"  Outside Schedule: {len(non_schedule)} mentions")

    return non_schedule


def main():
    schedule_rows = find_schedule_rows()
    if not schedule_rows:
        print("ERROR: No rows found for target company")
        return

    company_name = schedule_rows[0]["company_name"]
    category = schedule_rows[0]["investment_category"]

    total_fv = sum(float(r["fair_value"]) for r in schedule_rows if r["fair_value"])
    total_cost = sum(float(r["cost"]) for r in schedule_rows if r["cost"])
    inv_types = sorted(set(r["investment_type"] for r in schedule_rows))

    summary = {
        "total_fair_value_usd_thousands": total_fv,
        "total_cost_usd_thousands": total_cost,
        "num_investments": len(schedule_rows),
        "investment_types": inv_types,
        "category": category,
    }

    print()
    other_mentions = find_other_mentions(company_name)

    output = {
        "company_name": company_name,
        "schedule_rows": schedule_rows,
        "summary": summary,
        "other_filing_mentions": other_mentions,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {OUTPUT_PATH}\n")
    print("=" * 80)
    print(f"COMPANY: {company_name}")
    print(f"CATEGORY: {category}")
    print(f"=" * 80)

    print(f"\nSUMMARY:")
    print(f"  Total Fair Value:  ${total_fv:,.0f}K")
    print(f"  Total Cost:        ${total_cost:,.0f}K")
    print(f"  # Investments:     {len(schedule_rows)}")
    print(f"  Investment Types:  {', '.join(inv_types)}")

    print(f"\nSCHEDULE ROWS:")
    for i, r in enumerate(schedule_rows, 1):
        print(f"\n  [{i}] {r['investment_type']}")
        print(f"      Industry:        {r['industry']}")
        print(f"      Spread/Floor:    {r['rate_spread_floor'] or '—'}")
        print(f"      Rate Cash/PIK:   {r['rate_cash_pik'] or '—'}")
        print(f"      Investment Date: {r['investment_date'] or '—'}")
        print(f"      Maturity:        {r['maturity_date'] or '—'}")
        print(f"      Principal:       {r['principal_amount'] or '—'}")
        print(f"      Cost:            {r['cost'] or '—'}")
        print(f"      Fair Value:      {r['fair_value'] or '—'}")

    if other_mentions:
        print(f"\nOTHER FILING MENTIONS ({len(other_mentions)}):")
        for i, m in enumerate(other_mentions, 1):
            print(f"\n  [{i}] Section: {m['likely_section']}")
            snippet = m["snippet"]
            snippet = re.sub(
                r"(InductiveHealth)", r">>> \1 <<<", snippet, flags=re.IGNORECASE
            )
            print(f"      ...{snippet}...")
    else:
        print(f"\nNo additional mentions found outside the Schedule of Investments.")


if __name__ == "__main__":
    main()
