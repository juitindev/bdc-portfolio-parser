"""Tests for the regex-first / LLM-fallback rate parser.

All tests run offline — none of them require langchain or an API key.
The LLM path is exercised by structure (use_llm=True with a complete regex
result must not call out) but no live model is invoked.
"""
from bdc_parser.ai.rate_parser import (
    parse_rate,
    parse_rate_regex,
    _looks_incomplete,
)


class TestRegex:
    def test_fdus_full_floating(self):
        rt = parse_rate_regex("(S+7.75%) / (2.00%)", "11.71%/0.50%")
        assert rt.reference == "SOFR"
        assert rt.spread_pct == 7.75
        assert rt.floor_pct == 2.00
        assert rt.cash_pct == 11.71
        assert rt.pik_pct == 0.50
        assert rt.parsed_by == "regex"

    def test_prime_reference(self):
        rt = parse_rate_regex("(P+5.00%) / (1.50%)", "")
        assert rt.reference == "Prime"
        assert rt.spread_pct == 5.00
        assert rt.floor_pct == 1.50

    def test_fixed_single_rate(self):
        rt = parse_rate_regex("", "11.00%")
        assert rt.cash_pct == 11.00
        assert rt.reference is None
        assert rt.spread_pct is None

    def test_no_floor(self):
        rt = parse_rate_regex("(S+6.50%)", "10.00%/0.00%")
        assert rt.reference == "SOFR"
        assert rt.spread_pct == 6.50
        assert rt.floor_pct is None
        assert rt.cash_pct == 10.00
        assert rt.pik_pct == 0.0

    def test_generic_sofr_keyword(self):
        rt = parse_rate_regex("SOFR + 5.00%, 2.00% floor", "")
        assert rt.reference == "SOFR"
        assert rt.spread_pct == 5.00
        assert rt.floor_pct == 2.00

    def test_raw_field_captures_both_inputs(self):
        rt = parse_rate_regex("(S+7.75%)", "11.71%/0.50%")
        assert "(S+7.75%)" in rt.raw
        assert "11.71%/0.50%" in rt.raw


class TestParseRate:
    def test_empty_both(self):
        rt = parse_rate("", "")
        assert rt.parsed_by == "none"

    def test_em_dash_returns_none(self):
        rt = parse_rate("—", "—")
        assert rt.parsed_by == "none"

    def test_ascii_dash_returns_none(self):
        rt = parse_rate("-", "")
        assert rt.parsed_by == "none"

    def test_complete_skips_llm(self):
        # Regex result is complete, so use_llm=True should not trigger any
        # LLM call regardless of environment.
        rt = parse_rate("(S+7.75%) / (2.00%)", "11.71%/0.50%", use_llm=True)
        assert rt.parsed_by == "regex"
        assert rt.reference == "SOFR"

    def test_no_llm_flag_keeps_regex(self):
        rt = parse_rate("(S+7.75%) / (2.00%)", "11.71%/0.50%", use_llm=False)
        assert rt.parsed_by == "regex"

    def test_no_llm_with_incomplete_input_still_returns_regex(self):
        # Garbage string with no recognizable pattern — regex yields nothing.
        # With use_llm=False, we return the empty regex result (no crash).
        rt = parse_rate("variable", "", use_llm=False)
        assert rt.parsed_by == "regex"
        assert rt.reference is None


class TestLooksIncomplete:
    def test_floating_full_is_complete(self):
        from bdc_parser.models import RateTerms
        rt = RateTerms(reference="SOFR", spread_pct=7.75, cash_pct=11.71, raw="x")
        assert _looks_incomplete(rt) is False

    def test_fixed_rate_is_complete(self):
        from bdc_parser.models import RateTerms
        rt = RateTerms(cash_pct=12.0, raw="x")
        assert _looks_incomplete(rt) is False

    def test_only_spread_is_incomplete(self):
        from bdc_parser.models import RateTerms
        rt = RateTerms(spread_pct=7.75, raw="x")
        assert _looks_incomplete(rt) is True

    def test_only_floor_is_incomplete(self):
        from bdc_parser.models import RateTerms
        rt = RateTerms(floor_pct=2.0, raw="x")
        assert _looks_incomplete(rt) is True


class TestLLMGracefulDegradation:
    """The package must function with no langchain / no API key."""

    def test_llm_available_false_in_test_env(self, monkeypatch):
        # Ensure no API keys leak into the test
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        from bdc_parser.ai.llm import llm_available
        assert llm_available() is False

    def test_incomplete_input_with_no_llm_does_not_crash(self, monkeypatch):
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        rt = parse_rate("variable rate", "", use_llm=True)
        assert rt.parsed_by == "regex"  # fell back gracefully
