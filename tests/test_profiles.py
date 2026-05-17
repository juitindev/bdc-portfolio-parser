"""Tests for the BDC profile loader."""
import pytest

from bdc_parser.models import BDCProfile
from bdc_parser.profiles import load_profile, available_profiles


def test_load_fdus_returns_profile():
    p = load_profile("FDUS")
    assert isinstance(p, BDCProfile)
    assert p.ticker == "FDUS"
    assert p.name == "Fidus Investment Corporation"
    assert p.cik == "0001513363"


def test_case_insensitive():
    p1 = load_profile("FDUS")
    p2 = load_profile("fdus")
    p3 = load_profile("Fdus")
    assert p1.ticker == p2.ticker == p3.ticker


def test_missing_profile_raises_with_available_list():
    with pytest.raises(ValueError) as exc:
        load_profile("NONEXISTENT")
    msg = str(exc.value)
    assert "NONEXISTENT" in msg
    assert "FDUS" in msg  # the message should suggest what IS available


def test_available_profiles_contains_fdus():
    profiles = available_profiles()
    assert "FDUS" in profiles


def test_profile_has_only_thin_fields():
    """BDCProfile is intentionally minimal — no column map needed."""
    p = load_profile("FDUS")
    # Sanity: these are the only top-level fields we ever rely on.
    assert hasattr(p, "ticker")
    assert hasattr(p, "name")
    assert hasattr(p, "cik")
    assert hasattr(p, "notes")
    # And the model should NOT have grown a column map (per the design choice
    # that content-pattern extraction doesn't need one).
    assert not hasattr(p, "column_map")
