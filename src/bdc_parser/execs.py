"""Rank top executives extracted from a portfolio company website."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from bdc_parser.paths import website_json, execs_csv, execs_json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

LINKEDIN_STATUS = "deferred_tos_compliance"
LINKEDIN_NOTES = (
    "LinkedIn profile scraping deferred — ToS compliance consideration. "
    "Alternative compliant enrichment available via Apollo.io / Crunchbase "
    "if scoped."
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


def run(target: str, top: int = 3) -> Path:
    """Rank executives from the scraped website JSON; write CSV + JSON outputs."""
    website_path = website_json(target)
    out_csv = execs_csv(target)
    out_json = execs_json(target)

    with open(website_path, encoding="utf-8") as f:
        data = json.load(f)

    company_name = data.get("company_name") or target
    base_url = data.get("website", "")
    about_url = base_url.rstrip("/") + "/about-us/" if base_url else ""

    leaders = data["leadership"]
    print(f"Total executives from website: {len(leaders)}\n")

    scored = []
    for l in leaders:
        priority = rank_exec(l["title"])
        scored.append({**l, "priority": priority})

    scored.sort(key=lambda x: x["priority"])

    print("Full ranking:")
    for i, s in enumerate(scored, 1):
        marker = " ◀ SELECTED" if i <= top else ""
        print(f"  {i}. [P{s['priority']:>2}] {s['name']:<30} {s['title']}{marker}")

    top_n = scored[:top]

    records = []
    for rank, exec_data in enumerate(top_n, 1):
        records.append({
            "rank": rank,
            "name": exec_data["name"],
            "title": exec_data["title"],
            "source_url": about_url,
            "linkedin_status": LINKEDIN_STATUS,
            "linkedin_notes": LINKEDIN_NOTES,
            "notes": exec_data.get("bio", "") or "",
        })

    csv_fields = ["rank", "name", "title", "source_url", "linkedin_status", "linkedin_notes"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "company_name": company_name,
            "source_url": about_url,
            "scraped_at": data["scraped_at"],
            "executives": records,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to:")
    print(f"  CSV:  {out_csv}")
    print(f"  JSON: {out_json}")

    print(f"\n{'='*70}")
    print(f"FINAL TOP {top} EXECUTIVES")
    print(f"{'='*70}")
    for r in records:
        print(f"\n  #{r['rank']}  {r['name']}")
        print(f"      Title:    {r['title']}")
        print(f"      Source:   {r['source_url']}")
        print(f"      LinkedIn: {r['linkedin_status']}")

    return out_json
