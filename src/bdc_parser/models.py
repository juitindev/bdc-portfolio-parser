"""Pydantic models for BDC portfolio data."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RateTerms(BaseModel):
    """Structured form of a Schedule-of-Investments rate string."""
    reference: str | None = Field(None, description="e.g. SOFR, LIBOR, Prime")
    spread_pct: float | None = Field(None, description="spread over reference, %")
    floor_pct: float | None = Field(None, description="rate floor, %")
    cash_pct: float | None = Field(None, description="all-in cash rate, %")
    pik_pct: float | None = Field(None, description="PIK rate, %")
    raw: str = Field("", description="original unparsed rate string")
    parsed_by: str = Field("regex", description="regex | llm | none")


class Investment(BaseModel):
    """One row of a Schedule of Investments."""
    company_name: str
    industry: str | None = None
    investment_category: str | None = None
    investment_type: str | None = None
    rate_spread_floor: str | None = None
    rate_cash_pik: str | None = None
    rate: RateTerms | None = None
    investment_date: str | None = None
    maturity_date: str | None = None
    principal_amount: float | None = None
    cost: float | None = None
    fair_value: float | None = None


class BDCProfile(BaseModel):
    """Per-BDC parsing configuration.

    Intentionally thin: parsing uses content-pattern extraction, so no
    column map is needed. The profile only carries identity (ticker, name,
    CIK) and free-form notes.
    """
    ticker: str
    name: str
    cik: str
    notes: str | None = None
