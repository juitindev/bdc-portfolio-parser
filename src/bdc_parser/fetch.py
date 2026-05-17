"""Fetch FDUS latest 10-K filing and cache the raw HTML.

Migrated from src/fetch_filing.py — logic unchanged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# src/bdc_parser/fetch.py -> repo root is parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "raw"
CACHE_PATH = RAW_DIR / "fdus_10k_latest.html"

# edgartools requires a user-agent identity
os.environ.setdefault("EDGAR_IDENTITY", "Juit Chang ruitingz987@gmail.com")


def fetch_filing():
    from edgar import Company

    company = Company("FDUS")
    print(f"Company: {company.name} (CIK: {company.cik})")

    filings_10k = company.get_filings(form="10-K")
    latest = filings_10k[0]

    print(f"\nFiling metadata:")
    print(f"  Form:       {latest.form}")
    print(f"  Filed:      {latest.filing_date}")
    print(f"  Accession:  {latest.accession_no}")
    print(f"  Company:    {latest.company}")

    return latest


def save_html(filing) -> int:
    """Download and save the filing HTML. Returns file size in bytes."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    html = filing.html()
    CACHE_PATH.write_text(html, encoding="utf-8")
    size = CACHE_PATH.stat().st_size
    return size


def main():
    if CACHE_PATH.exists():
        size = CACHE_PATH.stat().st_size
        print(f"[CACHE HIT] Using cached HTML at {CACHE_PATH}")
        print(f"  File size: {size:,} bytes ({size / 1024 / 1024:.1f} MB)")
        print("\nTo re-fetch, delete the cache file and re-run.")
        return

    print("[CACHE MISS] Fetching from EDGAR...\n")
    filing = fetch_filing()

    print("\nDownloading HTML...")
    size = save_html(filing)
    print(f"  Saved to:   {CACHE_PATH}")
    print(f"  File size:  {size:,} bytes ({size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
