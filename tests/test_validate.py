"""Unit tests for validate.py — post-parse validation."""
import pytest

from bdc_parser.validate import (
    validate,
    ValidationReport,
    MAX_ROWS_PER_COMPANY,
)


def _row(**kw):
    """Build a row dict with sensible defaults; override with kwargs."""
    base = {
        "company_name": "Acme Corp",
        "industry": "Manufacturing",
        "investment_category": "Non-control/Non-affiliate",
        "investment_type": "First Lien Debt",
        "fair_value": "1000",
    }
    base.update(kw)
    return base


class TestEmptySchedule:
    def test_empty_rows_errors(self):
        r = validate([])
        assert not r.ok
        assert any(i.code == "EMPTY_SCHEDULE" for i in r.errors)


class TestBlankCompany:
    def test_missing_company_name_errors(self):
        rows = [_row(company_name=""), _row(company_name="")]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "BLANK_COMPANY" in codes

    def test_whitespace_only_is_blank(self):
        rows = [_row(company_name="   ")]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "BLANK_COMPANY" in codes

    def test_all_companies_named_ok(self):
        rows = [_row(company_name=f"Co {i}") for i in range(3)]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "BLANK_COMPANY" not in codes


class TestCompanyIsIndustry:
    def test_company_named_after_industry_errors(self):
        rows = [
            _row(company_name="Real Co", industry="Manufacturing"),
            _row(company_name="Manufacturing", industry="Manufacturing"),
        ]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "COMPANY_IS_INDUSTRY" in codes


class TestRunawayCompany:
    def test_too_many_rows_for_one_company_errors(self):
        rows = [_row(company_name="Acme")
                for _ in range(MAX_ROWS_PER_COMPANY + 1)]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "RUNAWAY_COMPANY" in codes

    def test_within_limit_ok(self):
        rows = [_row(company_name="Acme") for _ in range(5)]
        r = validate(rows)
        codes = [i.code for i in r.errors]
        assert "RUNAWAY_COMPANY" not in codes


class TestMultiCategory:
    def test_same_name_in_two_categories_warns(self):
        rows = [
            _row(company_name="Acme", investment_category="Control"),
            _row(company_name="Acme", investment_category="Affiliate"),
        ]
        r = validate(rows)
        codes = [i.code for i in r.warnings]
        assert "COMPANY_MULTI_CATEGORY" in codes


class TestTopConcentrated:
    def test_one_company_majority_warns(self):
        rows = [
            _row(company_name="Big", fair_value="9000"),
            _row(company_name="Small", fair_value="1000"),
        ]
        r = validate(rows)
        codes = [i.code for i in r.warnings]
        assert "TOP_COMPANY_CONCENTRATED" in codes

    def test_diversified_ok(self):
        rows = [_row(company_name=f"Co{i}", fair_value="100")
                for i in range(20)]
        r = validate(rows)
        codes = [i.code for i in r.warnings]
        assert "TOP_COMPANY_CONCENTRATED" not in codes


class TestUnknownRows:
    def test_unknown_rows_warns(self):
        r = validate([_row()], unknown_rows=[["junk"], ["more junk"]])
        codes = [i.code for i in r.warnings]
        assert "UNKNOWN_ROWS_PRESENT" in codes


class TestFDUSGoldenOutput:
    """Regression test against the committed FDUS CSV."""

    def test_committed_fdus_csv_passes_validation(self):
        import csv
        from bdc_parser.paths import schedule_csv

        path = schedule_csv("FDUS")
        if not path.exists():
            pytest.skip(f"FDUS CSV not present at {path}")
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        report = validate(rows)
        assert report.ok, (
            f"Errors on committed FDUS CSV: "
            f"{[(i.code, i.message) for i in report.errors]}"
        )
