"""Path helpers — all output filenames derive from ticker / target slug here."""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "raw"
DATA_DIR = PROJECT_ROOT / "data"


def slugify(s: str) -> str:
    """Lowercase + collapse non-alphanumerics to single underscore."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def cache_path(ticker: str) -> Path:
    return RAW_DIR / f"{ticker.lower()}_10k_latest.html"


def schedule_csv(ticker: str) -> Path:
    return DATA_DIR / f"{ticker.lower()}_schedule_full.csv"


def top10_csv(ticker: str) -> Path:
    return DATA_DIR / f"{ticker.lower()}_top10_by_fair_value.csv"


def deepdive_json(target: str) -> Path:
    return DATA_DIR / f"{slugify(target)}_filing_data.json"


def website_json(target: str) -> Path:
    return DATA_DIR / f"{slugify(target)}_website.json"


def execs_csv(target: str) -> Path:
    return DATA_DIR / f"{slugify(target)}_execs.csv"


def execs_json(target: str) -> Path:
    return DATA_DIR / f"{slugify(target)}_execs.json"
