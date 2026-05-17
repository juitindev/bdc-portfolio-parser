"""Parse Schedule-of-Investments rate strings.

Strategy: regex first. If regex leaves required fields empty AND an LLM
is available, escalate to the LLM. Otherwise return the regex result as-is.
The package works with no LLM dependencies installed and no API key —
the regex path is always available.
"""
from __future__ import annotations

import re

from bdc_parser.ai.llm import get_model, llm_available
from bdc_parser.models import RateTerms

# Reference rate abbreviations as they appear in FDUS-style strings: "(S+7.75%)"
_REF_ABBR = {"S": "SOFR", "P": "Prime", "L": "LIBOR", "B": "Base Rate"}

_ABBR_SPREAD = re.compile(r"\(\s*([SPLB])\s*\+\s*([\d.]+)\s*%\s*\)")
_REF_NAMES = re.compile(r"\b(SOFR|LIBOR|Prime|Base Rate)\b", re.I)
_GENERIC_SPREAD = re.compile(r"\+\s*([\d.]+)\s*%")
# FDUS floor lands as a standalone parenthesized rate after the spread group:
# "(S+7.75%) / (2.00%)"
_PAREN_FLOOR = re.compile(r"\)\s*/\s*\(\s*([\d.]+)\s*%\s*\)")
_GENERIC_FLOOR = re.compile(r"([\d.]+)\s*%\s*floor", re.I)
# Cash and PIK with explicit keywords
_CASH_WORD = re.compile(r"([\d.]+)\s*%\s*cash", re.I)
_PIK_WORD = re.compile(r"([\d.]+)\s*%\s*PIK", re.I)
# FDUS style two-number form: "11.71%/0.50%" or "11.71% / 0.50%" — cash/PIK
_CASH_SLASH_PIK = re.compile(r"^\s*([\d.]+)\s*%\s*/\s*([\d.]+)\s*%\s*$")
# Single fixed rate in cash_pik cell: "12.00%"
_SINGLE_RATE = re.compile(r"^\s*([\d.]+)\s*%\s*$")


def parse_rate_regex(spread_floor: str = "", cash_pik: str = "") -> RateTerms:
    """Apply pattern matching to the FDUS two-cell rate format.

    `spread_floor` is the variable-index/floor cell, `cash_pik` the cash/PIK cell.
    Either or both may be empty (equity rows have neither).
    """
    spread_floor = (spread_floor or "").strip()
    cash_pik = (cash_pik or "").strip()
    raw = " | ".join(p for p in (spread_floor, cash_pik) if p)
    rt = RateTerms(raw=raw, parsed_by="regex")

    if spread_floor:
        m = _ABBR_SPREAD.search(spread_floor)
        if m:
            rt.reference = _REF_ABBR.get(m.group(1).upper())
            rt.spread_pct = float(m.group(2))
        else:
            m_ref = _REF_NAMES.search(spread_floor)
            if m_ref:
                rt.reference = m_ref.group(1).upper()
            m_sp = _GENERIC_SPREAD.search(spread_floor)
            if m_sp:
                rt.spread_pct = float(m_sp.group(1))

        m = _PAREN_FLOOR.search(spread_floor)
        if m:
            rt.floor_pct = float(m.group(1))
        else:
            m = _GENERIC_FLOOR.search(spread_floor)
            if m:
                rt.floor_pct = float(m.group(1))

    if cash_pik:
        m = _CASH_SLASH_PIK.match(cash_pik)
        if m:
            rt.cash_pct = float(m.group(1))
            rt.pik_pct = float(m.group(2))
        else:
            m = _CASH_WORD.search(cash_pik)
            if m:
                rt.cash_pct = float(m.group(1))
            m = _PIK_WORD.search(cash_pik)
            if m:
                rt.pik_pct = float(m.group(1))
            if rt.cash_pct is None and rt.pik_pct is None:
                m = _SINGLE_RATE.match(cash_pik)
                if m:
                    rt.cash_pct = float(m.group(1))

    return rt


def _looks_incomplete(rt: RateTerms) -> bool:
    """A debt row should yield at least reference+spread (floating) or cash_pct (fixed)."""
    has_floating = rt.reference is not None and rt.spread_pct is not None
    has_fixed = rt.cash_pct is not None
    return not (has_floating or has_fixed)


_NULL_TOKENS = {"", "-", "--", "—", "—"}


def parse_rate(
    spread_floor: str = "",
    cash_pik: str = "",
    *,
    use_llm: bool = True,
) -> RateTerms:
    """Public entry point. Equity rows (no rate strings) return RateTerms(parsed_by='none')."""
    spread_floor = (spread_floor or "").strip()
    cash_pik = (cash_pik or "").strip()
    if spread_floor in _NULL_TOKENS:
        spread_floor = ""
    if cash_pik in _NULL_TOKENS:
        cash_pik = ""
    if not spread_floor and not cash_pik:
        return RateTerms(raw="", parsed_by="none")

    result = parse_rate_regex(spread_floor, cash_pik)
    if not use_llm or not _looks_incomplete(result):
        return result
    if not llm_available():
        return result
    return _parse_rate_llm(result.raw)


def _parse_rate_llm(raw: str) -> RateTerms:
    """LLM fallback using structured output."""
    model = get_model().with_structured_output(RateTerms)
    prompt = (
        "Extract the structured interest-rate terms from this BDC 10-K "
        "Schedule of Investments rate string. Use percentages as plain "
        "numbers (7.75 not 0.0775). If a field is absent, leave it null.\n"
        "Reference is the floating-rate index (e.g., SOFR, LIBOR, Prime, Base Rate).\n"
        "Spread is the basis-point margin above the reference, as a percent.\n"
        "Floor is the minimum reference rate, as a percent.\n"
        "Cash is the actual cash-pay interest rate, as a percent.\n"
        "PIK is the payment-in-kind interest rate, as a percent.\n\n"
        f"Rate string: {raw!r}"
    )
    rt: RateTerms = model.invoke(prompt)
    rt.raw = raw
    rt.parsed_by = "llm"
    return rt
