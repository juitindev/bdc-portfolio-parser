"""Rank a BDC's portfolio companies by total fair value (summed across investment rows)."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from bdc_parser.models import BDCProfile
from bdc_parser.paths import schedule_csv, top10_csv


def run(profile: BDCProfile, top: int = 10) -> Path:
    """Aggregate per-company fair value, write the top-N CSV. Returns output path."""
    input_path = schedule_csv(profile.ticker)
    output_path = top10_csv(profile.ticker)

    with open(input_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    companies: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        companies[r["company_name"]].append(r)

    aggregated = []
    for name, inv_rows in companies.items():
        total_fv = sum(float(r["fair_value"]) for r in inv_rows if r["fair_value"])
        total_cost = sum(float(r["cost"]) for r in inv_rows if r["cost"])
        inv_types = sorted(set(r["investment_type"] for r in inv_rows))
        industry = inv_rows[0]["industry"]
        category = inv_rows[0]["investment_category"]

        aggregated.append({
            "company_name": name,
            "industry": industry,
            "investment_category": category,
            "total_fair_value": total_fv,
            "total_cost": total_cost,
            "num_investments": len(inv_rows),
            "investment_types": "; ".join(inv_types),
        })

    aggregated.sort(key=lambda x: x["total_fair_value"], reverse=True)

    for i, a in enumerate(aggregated, 1):
        a["rank"] = i

    top_rows = aggregated[:top]
    fieldnames = [
        "rank", "company_name", "industry", "investment_category",
        "total_fair_value", "total_cost", "num_investments", "investment_types",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(top_rows)

    print(f"Total companies: {len(aggregated)}")
    print(f"Top {top} saved to {output_path}\n")

    print(f"{'Rank':<5} {'Company':<50} {'Industry':<30} {'Cat':<12} {'#Inv':>5} "
          f"{'Cost':>12} {'Fair Value':>12}")
    print("-" * 130)
    for a in top_rows:
        print(f"{a['rank']:<5} {a['company_name'][:49]:<50} {a['industry'][:29]:<30} "
              f"{a['investment_category'][:11]:<12} {a['num_investments']:>5} "
              f"${a['total_cost']:>10,.0f} ${a['total_fair_value']:>10,.0f}")
        print(f"      Types: {a['investment_types']}")
        print()

    runners_lo = top
    runners_hi = top + 10
    if runners_hi <= len(aggregated):
        print(f"\nRunners-up (rank {runners_lo + 1}-{runners_hi}):")
        print(f"{'Rank':<5} {'Company':<50} {'Fair Value':>12} {'#Inv':>5} {'Types'}")
        print("-" * 110)
        for a in aggregated[runners_lo:runners_hi]:
            print(f"{a['rank']:<5} {a['company_name'][:49]:<50} ${a['total_fair_value']:>10,.0f} "
                  f"{a['num_investments']:>5} {a['investment_types']}")

    total_fv_all = sum(a["total_fair_value"] for a in aggregated)
    top_fv = sum(a["total_fair_value"] for a in top_rows)
    print(f"\nConcentration: top {top} = ${top_fv:,.0f}K of ${total_fv_all:,.0f}K "
          f"({top_fv/total_fv_all*100:.1f}% of portfolio)")

    return output_path
