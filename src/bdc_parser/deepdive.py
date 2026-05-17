"""Extract all filing data for one portfolio company from the Schedule CSV + raw 10-K HTML."""
from __future__ import annotations

import csv
import json
import re
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from bdc_parser.models import BDCProfile
from bdc_parser.paths import cache_path, schedule_csv, deepdive_json

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def find_schedule_rows(csv_path: Path, target: str) -> list[dict]:
    """Filter CSV rows whose company_name contains the target substring (case-insensitive)."""
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    target_lc = target.lower()
    matches = [r for r in rows if target_lc in r["company_name"].lower()]
    print(f"Found {len(matches)} schedule rows for target '{target}'")

    cleaned = []
    for r in matches:
        cleaned.append({k: (v if v else None) for k, v in r.items()})
    return cleaned


def find_other_mentions(html_path: Path, target: str) -> list[dict]:
    """Search the full 10-K HTML for mentions of the target outside the Schedule tables.

    Returns context snippets with ±200 chars around each match.
    """
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    full_text = soup.get_text(separator=" ")
    full_text = re.sub(r"\s+", " ", full_text)

    pattern = re.compile(re.escape(target), re.IGNORECASE)
    matches = list(pattern.finditer(full_text))
    print(f"Total mentions of '{target}' in full text: {len(matches)}")

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


def run(profile: BDCProfile, target: str) -> Path | None:
    """Extract deep-dive filing data for one portfolio company. Returns output path."""
    csv_path = schedule_csv(profile.ticker)
    html_path = cache_path(profile.ticker)
    out_path = deepdive_json(target)

    schedule_rows = find_schedule_rows(csv_path, target)
    if not schedule_rows:
        print(f"ERROR: No rows in {csv_path.name} match target '{target}'")
        return None

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
    other_mentions = find_other_mentions(html_path, target)

    output = {
        "company_name": company_name,
        "schedule_rows": schedule_rows,
        "summary": summary,
        "other_filing_mentions": other_mentions,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {out_path}\n")
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
        marker_re = re.compile(re.escape(target), re.IGNORECASE)
        for i, m in enumerate(other_mentions, 1):
            print(f"\n  [{i}] Section: {m['likely_section']}")
            snippet = marker_re.sub(lambda mm: f">>> {mm.group(0)} <<<", m["snippet"])
            print(f"      ...{snippet}...")
    else:
        print(f"\nNo additional mentions found outside the Schedule of Investments.")

    return out_path
