"""BDC profile loader."""
from __future__ import annotations

import importlib.resources as res

import yaml

from bdc_parser.models import BDCProfile


def load_profile(ticker: str) -> BDCProfile:
    """Load a BDCProfile by ticker (case-insensitive)."""
    fname = f"{ticker.lower()}.yaml"
    files = res.files("bdc_parser.profiles")
    target = files / fname
    if not target.is_file():
        raise ValueError(
            f"No profile for '{ticker}'. Available: {', '.join(available_profiles())}"
        )
    return BDCProfile.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")))


def available_profiles() -> list[str]:
    """List ticker names of available profile YAML files."""
    files = res.files("bdc_parser.profiles")
    return sorted(
        p.name[:-5].upper()
        for p in files.iterdir()
        if p.name.endswith(".yaml")
    )
