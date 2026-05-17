"""Unit tests for parse.py — row classification and field extraction.

Covers the heuristic-driven pieces of the parser. Whole-pipeline parity
with the FDUS filing is validated separately (the committed
data/fdus_schedule_full.csv was produced by this code).
"""
from bdc_parser.parse import (
    classify_row,
    clean_amount,
    extract_investment_fields,
    strip_footnotes,
)
from bdc_parser.locate import find_schedule_groups


class TestStripFootnotes:
    def test_simple_footnote(self):
        assert strip_footnotes("Acme Corp (a)") == "Acme Corp"

    def test_double_letter_footnote(self):
        assert strip_footnotes("Acme Corp (am)") == "Acme Corp"

    def test_triple_letter_footnote(self):
        assert strip_footnotes("Acme Corp (abc)") == "Acme Corp"

    def test_preserves_dba(self):
        result = strip_footnotes("Holdings Co (dba Acme Trading) (a)")
        assert "(dba Acme Trading)" in result

    def test_removes_fka(self):
        result = strip_footnotes("New Name (fka Old Name)")
        assert "fka" not in result
        assert "Old Name" not in result

    def test_company_starting_with_digit(self):
        assert strip_footnotes("2KDirect, Inc. (a)") == "2KDirect, Inc."


class TestCleanAmount:
    def test_strips_commas(self):
        assert clean_amount("1,234") == "1234"

    def test_strips_dollar_sign(self):
        assert clean_amount("$1,234") == "1234"

    def test_parenthesized_is_negative(self):
        assert clean_amount("(14)") == "-14"

    def test_em_dash_is_empty(self):
        assert clean_amount("—") == ""

    def test_empty_stays_empty(self):
        assert clean_amount("") == ""


class TestClassifyRow:
    def test_header(self):
        assert classify_row(["Portfolio Company", "Investment Type", "Industry"]) == "HEADER"

    def test_section_control(self):
        assert classify_row(["Control Investments (t)"]) == "SECTION"

    def test_section_non_control(self):
        assert classify_row(["Non-control/Non-affiliate Investments"]) == "SECTION"

    def test_total(self):
        assert classify_row(["Total Investments", "", "1,234,567"]) == "TOTAL"

    def test_empty(self):
        assert classify_row(["", "", ""]) == "EMPTY"

    def test_company(self):
        # 2 non-empty cells, second is industry text (not a date/rate/amount)
        assert classify_row(["Acme Corp", "Manufacturing"]) == "COMPANY"

    def test_invest(self):
        cells = ["First Lien Debt", "(S+7.75%)", "11.71%/0.50%",
                 "1/15/2024", "1/15/2029", "1,000", "990", "1,050"]
        assert classify_row(cells) == "INVEST"


class TestExtractInvestmentFields:
    def test_debt_row_full(self):
        cells = ["First Lien Debt", "(S+7.75%) / (2.00%)", "11.71%/0.50%",
                 "1/15/2024", "1/15/2029",
                 "$", "1,000", "$", "990", "$", "1,050"]
        f = extract_investment_fields(cells)
        assert f["investment_type"] == "First Lien Debt"
        assert f["rate_spread_floor"] == "(S+7.75%) / (2.00%)"
        assert f["rate_cash_pik"] == "11.71%/0.50%"
        assert f["investment_date"] == "1/15/2024"
        assert f["maturity_date"] == "1/15/2029"
        assert f["principal_amount"] == "1000"
        assert f["cost"] == "990"
        assert f["fair_value"] == "1050"

    def test_equity_row_two_amounts(self):
        # equity rows have no principal — only cost + fair_value
        cells = ["Common Equity", "", "", "1/15/2024", "",
                 "$", "—", "$", "150"]
        f = extract_investment_fields(cells)
        assert f["investment_type"] == "Common Equity"
        assert f["principal_amount"] == ""
        assert f["fair_value"] == "150"

    def test_strips_unit_count_from_type(self):
        cells = ["Common Equity (1,000units)", "", "", "1/15/2024", "",
                 "$", "100", "$", "150"]
        f = extract_investment_fields(cells)
        assert f["investment_type"] == "Common Equity"


class TestFindScheduleGroups:
    def test_detects_minimal_fixture(self, fdus_schedule_html):
        groups = find_schedule_groups(fdus_schedule_html)
        assert len(groups) == 1
        assert groups[0].start == 0
        assert groups[0].header_table == 0

    def test_empty_html_no_groups(self):
        assert find_schedule_groups("<html></html>") == []
