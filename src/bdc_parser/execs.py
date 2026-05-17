"""Finalize top 3 executives for InductiveHealth Informatics deliverable.

Migrated from src/finalize_execs.py — logic unchanged.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEBSITE_JSON = PROJECT_ROOT / "data" / "inductivehealth_website.json"
OUTPUT_CSV = PROJECT_ROOT / "data" / "inductivehealth_execs.csv"
OUTPUT_JSON = PROJECT_ROOT / "data" / "inductivehealth_execs.json"

ABOUT_URL = "https://inductivehealth.com/about-us/"

LINKEDIN_STATUS = "deferred_tos_compliance"
LINKEDIN_NOTES = (
    "LinkedIn profile scraping deferred per client discussion — "
    "ToS compliance consideration. Alternative compliant enrichment "
    "available via Apollo.io / Crunchbase if scoped."
)

TITLE_PRIORITY = [
    (1, ["chief executive officer", "ceo", "president"]),
    (2, ["chief financial officer", "cfo"]),
    (3, ["chief operating officer", "coo"]),
    (4, ["chief technology officer", "cto"]),
    (5, ["chief information officer", "cio"]),
    (6, ["chief information security officer", "ciso"]),
    (7, ["chief marketing officer", "cmo", "chief revenue officer", "cro"]),
    (8, ["chief", "c-level"]),
    (9, ["executive vice president", "evp"]),
    (10, ["senior vice president", "svp"]),
    (11, ["vice president", "vp"]),
    (12, ["general manager"]),
    (13, ["director"]),
]


def rank_exec(title: str) -> int:
    """Return priority score for a title (lower = more senior).

    Checks VP/EVP/SVP first so "Vice President" doesn't false-match
    the "president" keyword in tier 1.
    """
    t = title.lower()

    if "executive vice president" in t or "evp" in t:
        return 9
    if "senior vice president" in t or "svp" in t:
        return 10
    if "vice president" in t or "vp " in t or t.endswith(" vp"):
        return 11

    for priority, keywords in TITLE_PRIORITY:
        if priority >= 9:
            continue
        if any(kw in t for kw in keywords):
            return priority
    return 99


def main():
    with open(WEBSITE_JSON, encoding="utf-8") as f:
        data = json.load(f)

    leaders = data["leadership"]
    print(f"Total executives from website: {len(leaders)}\n")

    scored = []
    for l in leaders:
        priority = rank_exec(l["title"])
        scored.append({**l, "priority": priority})

    scored.sort(key=lambda x: x["priority"])

    print("Full ranking:")
    for i, s in enumerate(scored, 1):
        marker = " ◀ SELECTED" if i <= 3 else ""
        print(f"  {i}. [P{s['priority']:>2}] {s['name']:<30} {s['title']}{marker}")

    top3 = scored[:3]

    records = []
    for rank, exec_data in enumerate(top3, 1):
        records.append({
            "rank": rank,
            "name": exec_data["name"],
            "title": exec_data["title"],
            "source_url": ABOUT_URL,
            "linkedin_status": LINKEDIN_STATUS,
            "linkedin_notes": LINKEDIN_NOTES,
            "notes": exec_data.get("bio", "") or "",
        })

    csv_fields = ["rank", "name", "title", "source_url", "linkedin_status", "linkedin_notes"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "company_name": "InductiveHealth Informatics",
            "source_url": ABOUT_URL,
            "scraped_at": data["scraped_at"],
            "executives": records,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to:")
    print(f"  CSV:  {OUTPUT_CSV}")
    print(f"  JSON: {OUTPUT_JSON}")

    print(f"\n{'='*70}")
    print(f"FINAL TOP 3 EXECUTIVES")
    print(f"{'='*70}")
    for r in records:
        print(f"\n  #{r['rank']}  {r['name']}")
        print(f"      Title:    {r['title']}")
        print(f"      Source:   {r['source_url']}")
        print(f"      LinkedIn: {r['linkedin_status']}")


if __name__ == "__main__":
    main()
