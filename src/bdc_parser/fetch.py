"""Fetch a BDC 10-K filing from SEC EDGAR and cache the raw HTML."""
from __future__ import annotations

import os
from pathlib import Path

from bdc_parser.models import BDCProfile
from bdc_parser.paths import cache_path, RAW_DIR

# edgartools requires a user-agent identity. Override via EDGAR_IDENTITY env var.
os.environ.setdefault("EDGAR_IDENTITY", "BDC Portfolio Parser parser@example.com")


def fetch_filing(profile: BDCProfile):
    """Fetch the latest 10-K filing object for the given BDC."""
    from edgar import Company

    company = Company(profile.cik or profile.ticker)
    print(f"Company: {company.name} (CIK: {company.cik})")

    filings_10k = company.get_filings(form="10-K")
    latest = filings_10k[0]

    print(f"\nFiling metadata:")
    print(f"  Form:       {latest.form}")
    print(f"  Filed:      {latest.filing_date}")
    print(f"  Accession:  {latest.accession_no}")
    print(f"  Company:    {latest.company}")

    return latest


def save_html(filing, dest: Path) -> int:
    """Download and save the filing HTML. Returns file size in bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    html = filing.html()
    dest.write_text(html, encoding="utf-8")
    return dest.stat().st_size


def run(profile: BDCProfile, force: bool = False) -> Path:
    """Fetch and cache the latest 10-K. Returns the cache path."""
    dest = cache_path(profile.ticker)
    if dest.exists() and not force:
        size = dest.stat().st_size
        print(f"[CACHE HIT] Using cached HTML at {dest}")
        print(f"  File size: {size:,} bytes ({size / 1024 / 1024:.1f} MB)")
        print("\nTo re-fetch, pass --force or delete the cache file.")
        return dest

    print("[CACHE MISS] Fetching from EDGAR...\n")
    filing = fetch_filing(profile)

    print("\nDownloading HTML...")
    size = save_html(filing, dest)
    print(f"  Saved to:   {dest}")
    print(f"  File size:  {size:,} bytes ({size / 1024 / 1024:.1f} MB)")
    return dest
