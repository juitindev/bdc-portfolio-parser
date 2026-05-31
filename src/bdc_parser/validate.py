"""Post-parse validation of a parsed Schedule of Investments.

Profile-independent. Runs against the in-memory rows that parse.run()
builds, before/after CSV write. Returns a ValidationReport; the caller
decides whether to fail.

The validator catches silent parsing corruption — the bug class where
rows still get written but with wrong attribution (company name absent,
runaway aggregation, section-boundary drift). It is also the gate used
by the qa/ eval harness: if validate() fails, no point running RAG eval
on the filing.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class ValidationIssue:
    level: str                                       # "error" | "warning"
    code: str                                        # stable short id
    message: str                                     # human-readable
    rows: list[int] = field(default_factory=list)   # 1-based CSV row indices


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


MAX_ROWS_PER_COMPANY = 50
MAX_TOP_COMPANY_SHARE = 0.40


def _safe_float(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def validate(rows: list[dict], unknown_rows: list | None = None) -> ValidationReport:
    """Run all checks against parsed Schedule of Investments rows.

    `rows` matches the dict shape produced by parse.run()'s rows_out.
    `unknown_rows` is the optional collection of unclassifiable rows
    captured during parsing.
    """
    report = ValidationReport()

    if not rows:
        report.issues.append(ValidationIssue(
            "error", "EMPTY_SCHEDULE",
            "No investment rows parsed — either an empty filing or a "
            "classifier failure that left every row unrouted.",
        ))
        return report

    blank_rows = [i for i, r in enumerate(rows, start=1)
                  if not (r.get("company_name") or "").strip()]
    if blank_rows:
        report.issues.append(ValidationIssue(
            "error", "BLANK_COMPANY",
            f"{len(blank_rows)} rows have empty company_name "
            f"(attribution did not advance — INVEST rows orphaned).",
            rows=blank_rows,
        ))

    industries = {(r.get("industry") or "").strip()
                  for r in rows if (r.get("industry") or "").strip()}
    misclassified = [(i, r["company_name"]) for i, r in enumerate(rows, start=1)
                     if (r.get("company_name") or "").strip() in industries]
    if misclassified:
        sample = sorted({c for _, c in misclassified})[:5]
        report.issues.append(ValidationIssue(
            "error", "COMPANY_IS_INDUSTRY",
            f"{len(misclassified)} rows have company_name matching a known "
            f"industry value (likely a COMPANY/SECTION misclassification): "
            f"{sample}.",
            rows=[i for i, _ in misclassified],
        ))

    per_company = Counter((r.get("company_name") or "").strip() for r in rows)
    runaway = [(name, n) for name, n in per_company.items()
               if name and n > MAX_ROWS_PER_COMPANY]
    if runaway:
        runaway.sort(key=lambda x: -x[1])
        report.issues.append(ValidationIssue(
            "error", "RUNAWAY_COMPANY",
            f"{len(runaway)} companies have > {MAX_ROWS_PER_COMPANY} rows "
            f"(attribution-stuck symptom): {runaway[:3]}.",
        ))

    cats: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        name = (r.get("company_name") or "").strip()
        cat = (r.get("investment_category") or "").strip()
        if name and cat:
            cats[name].add(cat)
    multi = {n: c for n, c in cats.items() if len(c) > 1}
    if multi:
        sample = list(multi.items())[:3]
        report.issues.append(ValidationIssue(
            "warning", "COMPANY_MULTI_CATEGORY",
            f"{len(multi)} companies span multiple investment_categories "
            f"(usually a section-boundary drift): {sample}.",
        ))

    fv_by_company: dict[str, float] = defaultdict(float)
    for r in rows:
        name = (r.get("company_name") or "").strip()
        if name:
            fv_by_company[name] += _safe_float(r.get("fair_value"))
    total_fv = sum(fv_by_company.values())
    if total_fv > 0 and fv_by_company:
        top_name, top_fv = max(fv_by_company.items(), key=lambda kv: kv[1])
        share = top_fv / total_fv
        if share > MAX_TOP_COMPANY_SHARE:
            report.issues.append(ValidationIssue(
                "warning", "TOP_COMPANY_CONCENTRATED",
                f"Top company '{top_name}' is {share:.1%} of portfolio "
                f"fair value (> {MAX_TOP_COMPANY_SHARE:.0%}) — unusual "
                f"for a diversified BDC; may indicate aggregation bug.",
            ))

    blank_industry = [i for i, r in enumerate(rows, start=1)
                      if not (r.get("industry") or "").strip()]
    if blank_industry:
        report.issues.append(ValidationIssue(
            "warning", "BLANK_INDUSTRY",
            f"{len(blank_industry)} rows have no industry value "
            f"(COMPANY row matched without industry cell).",
            rows=blank_industry,
        ))

    if unknown_rows:
        report.issues.append(ValidationIssue(
            "warning", "UNKNOWN_ROWS_PRESENT",
            f"{len(unknown_rows)} rows could not be classified by the "
            f"parser. Inspect parse.run()'s unknown_rows output to decide "
            f"if they should be parsed.",
        ))

    return report


def print_report(report: ValidationReport) -> None:
    """Print a human-readable summary."""
    if report.ok and not report.warnings:
        print("Validation: OK")
        return
    for issue in report.issues:
        marker = "ERROR" if issue.level == "error" else "WARN "
        print(f"[{marker}] {issue.code}: {issue.message}")
        if issue.rows:
            head = issue.rows[:5]
            suffix = f" … +{len(issue.rows) - 5} more" if len(issue.rows) > 5 else ""
            print(f"         (rows {head}{suffix})")
    print(f"Validation: {len(report.errors)} error(s), "
          f"{len(report.warnings)} warning(s)")
