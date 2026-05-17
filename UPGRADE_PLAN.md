# BDC Portfolio Parser — Upgrade Plan

Goal: turn the one-off FDUS sample scripts into a reusable, installable package
with a CLI, multi-BDC support, and an optional LLM-assisted rate-string parser.

- Repo name: `bdc-portfolio-parser` (rename from `fdus-portfolio-parser`)
- Package name: `bdc_parser`
- CLI command: `bdc-parse`
- LLM layer: provider-agnostic, fallback-only (regex first, LLM on low confidence)

---

## 1. Target structure

```
bdc-portfolio-parser/
├── pyproject.toml
├── README.md
├── methodology.md
├── UPGRADE_PLAN.md          # this file
├── .github/workflows/ci.yml
├── src/bdc_parser/
│   ├── __init__.py
│   ├── cli.py               # argparse entry point
│   ├── models.py            # Pydantic: Investment, RateTerms, BDCProfile
│   ├── fetch.py             # was fetch_filing.py — takes CIK/ticker
│   ├── locate.py            # was locate_schedule.py
│   ├── parse.py             # was parse_schedule.py — takes a BDCProfile
│   ├── rank.py              # was rank_top_companies.py
│   ├── deepdive.py          # was extract_company_filing_data.py
│   ├── profiles/
│   │   ├── __init__.py      # load_profile(ticker) -> BDCProfile
│   │   ├── fdus.yaml
│   │   ├── main.yaml        # Main Street Capital (stub, tune later)
│   │   └── arcc.yaml        # Ares Capital (stub, tune later)
│   └── ai/
│       ├── __init__.py
│       ├── rate_parser.py   # regex-first, LLM-fallback rate parsing
│       └── llm.py           # provider-agnostic LLM factory
├── tests/
│   ├── conftest.py
│   ├── fixtures/            # trimmed HTML table snippets
│   ├── test_parse.py
│   ├── test_rank.py
│   ├── test_profiles.py
│   └── test_rate_parser.py
└── data/                    # keep existing FDUS outputs as the sample
```

Migration note: `scrape_company_website.py` and `finalize_execs.py` can stay as
`deepdive.py` helpers or their own modules — they are not the focus of this
upgrade. Keep their logic intact, just move them under the package.

---

## 2. Design decisions (read before coding)

### 2a. BDCProfile abstraction
Each BDC's 10-K Schedule of Investments differs in column order, footnote
conventions, and how the table is located in the HTML. Capture those
differences in a YAML profile so `parse.py` stays generic.

The core parser takes a `BDCProfile` and never hardcodes "FDUS" anywhere.

### 2b. AI layer = fallback only
`rate_parser.parse_rate()` runs a regex parser first. The LLM is called ONLY
when the regex result is missing fields or low confidence. Consequences:
- Most rows cost zero tokens.
- The package works with no API key and no `langchain` installed — regex path
  is always available. The LLM is an optional extra.
- CI tests run offline by mocking the LLM; one optional live test is marked
  `@pytest.mark.llm` and skipped unless a key is present.

This "don't use AI where regex suffices" design is itself a selling point —
mention it in the README and in client proposals.

### 2c. Provider-agnostic LLM
Use `init_chat_model` with the `provider:model` string format. Switching
provider (Anthropic / OpenAI / etc.) is a one-line config change, no code edit.

---

## 3. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "bdc-portfolio-parser"
version = "1.0.0"
description = "SEC EDGAR BDC 10-K Schedule of Investments parser with optional LLM-assisted rate parsing."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Jui Ting Chang" }]
dependencies = [
    "edgartools>=5.30.0",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "requests>=2.31",
    "pydantic>=2.6",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
# LLM layer is opt-in. Install one provider extra to enable it.
ai = ["langchain>=1.0"]
anthropic = ["langchain>=1.0", "langchain-anthropic>=0.3"]
openai = ["langchain>=1.0", "langchain-openai>=0.3"]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[project.scripts]
bdc-parse = "bdc_parser.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/bdc_parser"]

[tool.pytest.ini_options]
markers = [
    "llm: tests that call a live LLM (skipped unless an API key is set)",
]
```

Pin `langchain>=1.0` — the 1.x line is the current API (`from langchain.chat_models
import init_chat_model`). Verify the exact latest version when you run this.

---

## 4. models.py

```python
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
    raw: str = Field(..., description="original unparsed rate string")
    parsed_by: str = Field("regex", description="regex | llm | none")


class Investment(BaseModel):
    """One row of a Schedule of Investments."""
    company_name: str
    industry: str | None = None
    investment_category: str | None = None  # Control / Affiliate / Non-control
    investment_type: str | None = None
    rate: RateTerms | None = None
    investment_date: str | None = None
    maturity_date: str | None = None
    principal_amount: float | None = None
    cost: float | None = None
    fair_value: float | None = None


class ColumnMap(BaseModel):
    """Maps a BDC's column headers to canonical Investment fields."""
    company_name: str
    industry: str | None = None
    investment_type: str | None = None
    rate: str | None = None
    investment_date: str | None = None
    maturity_date: str | None = None
    principal_amount: str | None = None
    cost: str | None = None
    fair_value: str | None = None


class BDCProfile(BaseModel):
    """Per-BDC parsing configuration loaded from YAML."""
    ticker: str
    name: str
    cik: str
    schedule_anchor: str = Field(
        ..., description="text/heading used to locate the Schedule of Investments"
    )
    column_map: ColumnMap
    notes: str | None = None
```

---

## 5. profiles/fdus.yaml

Fill `column_map` from the *actual* FDUS header text in the filing — the values
below are the canonical field names you described in the README; the YAML
*values* must be the literal header strings as they appear in the HTML so the
parser can match them.

```yaml
ticker: FDUS
name: Fidus Investment Corporation
cik: "0001513363"
schedule_anchor: "Schedule of Investments"
column_map:
  company_name: "Portfolio Company"
  industry: "Industry"
  investment_type: "Type of Investment"
  rate: "Interest Rate"
  investment_date: "Initial Acquisition Date"
  maturity_date: "Maturity Date"
  principal_amount: "Principal"
  cost: "Cost"
  fair_value: "Fair Value"
notes: >
  FY2025 10-K, accession 0001193125-26-076572. Three categories per
  Investment Company Act 2(a)(3): Control / Affiliate / Non-control.
```

`profiles/__init__.py`:

```python
"""Profile loader."""
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
        available = sorted(
            p.name[:-5] for p in files.iterdir() if p.name.endswith(".yaml")
        )
        raise ValueError(
            f"No profile for '{ticker}'. Available: {', '.join(available)}"
        )
    return BDCProfile.model_validate(yaml.safe_load(target.read_text()))
```

---

## 6. ai/llm.py — provider-agnostic factory

```python
"""Provider-agnostic LLM factory. Import is lazy so the package works
without langchain installed."""
from __future__ import annotations

import os

# Default model string in "provider:model" form. Override via BDC_PARSER_MODEL.
DEFAULT_MODEL = os.environ.get("BDC_PARSER_MODEL", "anthropic:claude-sonnet-4-6")


def llm_available() -> bool:
    """True if langchain is importable and an API key is set."""
    try:
        import langchain  # noqa: F401
    except ImportError:
        return False
    return any(
        os.environ.get(k)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY")
    )


def get_model(model: str | None = None):
    """Return a configured chat model. Raises if langchain is missing."""
    from langchain.chat_models import init_chat_model

    return init_chat_model(model or DEFAULT_MODEL, temperature=0)
```

Verify `init_chat_model`'s import path and the current model string when you
run this — LangChain's package layout shifts between minor versions.

---

## 7. ai/rate_parser.py — regex-first, LLM-fallback

```python
"""Parse Schedule-of-Investments rate strings.

Strategy: regex first. If regex leaves required fields empty AND an LLM is
available, escalate to the LLM. Otherwise return the regex result as-is.
"""
from __future__ import annotations

import re

from bdc_parser.ai.llm import get_model, llm_available
from bdc_parser.models import RateTerms

_REF = re.compile(r"\b(SOFR|LIBOR|Prime|Base Rate)\b", re.I)
_SPREAD = re.compile(r"\+\s*([\d.]+)\s*%")
_FLOOR = re.compile(r"([\d.]+)\s*%\s*floor", re.I)
_CASH = re.compile(r"([\d.]+)\s*%\s*cash", re.I)
_PIK = re.compile(r"([\d.]+)\s*%\s*PIK", re.I)


def _f(m: re.Match | None) -> float | None:
    return float(m.group(1)) if m else None


def parse_rate_regex(raw: str) -> RateTerms:
    ref = _REF.search(raw)
    return RateTerms(
        reference=ref.group(1).upper() if ref else None,
        spread_pct=_f(_SPREAD.search(raw)),
        floor_pct=_f(_FLOOR.search(raw)),
        cash_pct=_f(_CASH.search(raw)),
        pik_pct=_f(_PIK.search(raw)),
        raw=raw,
        parsed_by="regex",
    )


def _looks_incomplete(rt: RateTerms) -> bool:
    """A debt row should at least yield a reference + spread, or a cash rate."""
    has_floating = rt.reference is not None and rt.spread_pct is not None
    has_fixed = rt.cash_pct is not None
    return not (has_floating or has_fixed)


def parse_rate(raw: str, use_llm: bool = True) -> RateTerms:
    """Public entry point. Equity rows (empty rate) return an empty RateTerms."""
    raw = (raw or "").strip()
    if not raw or raw in {"-", "--", "—"}:
        return RateTerms(raw=raw, parsed_by="none")

    result = parse_rate_regex(raw)
    if not use_llm or not _looks_incomplete(result):
        return result
    if not llm_available():
        return result  # graceful: regex result, no crash
    return _parse_rate_llm(raw)


def _parse_rate_llm(raw: str) -> RateTerms:
    """LLM fallback using structured output."""
    model = get_model().with_structured_output(RateTerms)
    prompt = (
        "Extract the structured interest-rate terms from this BDC 10-K "
        "Schedule of Investments rate string. Use percentages as plain "
        "numbers (7.75 not 0.0775). If a field is absent, leave it null.\n\n"
        f"Rate string: {raw!r}"
    )
    rt: RateTerms = model.invoke(prompt)
    rt.raw = raw
    rt.parsed_by = "llm"
    return rt
```

---

## 8. cli.py

```python
"""bdc-parse command-line interface."""
from __future__ import annotations

import argparse
import sys

from bdc_parser.profiles import load_profile


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bdc-parse", description="BDC 10-K parser")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("fetch", help="fetch + cache a BDC 10-K from EDGAR")
    sp.add_argument("ticker")

    sp = sub.add_parser("schedule", help="parse the Schedule of Investments")
    sp.add_argument("ticker")
    sp.add_argument("--out", default=None)
    sp.add_argument("--no-llm", action="store_true", help="disable LLM rate fallback")

    sp = sub.add_parser("rank", help="rank portfolio companies by fair value")
    sp.add_argument("ticker")
    sp.add_argument("--top", type=int, default=10)

    sp = sub.add_parser("profiles", help="list available BDC profiles")

    args = p.parse_args(argv)

    if args.cmd == "profiles":
        # list logic here
        print("FDUS, MAIN, ARCC")
        return 0

    if args.cmd != "profiles":
        profile = load_profile(args.ticker)  # raises clear error if missing
        # dispatch to fetch / parse / rank using `profile`
        # wire these to the migrated module functions
        ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The `...` blocks are where the migrated logic from the old scripts plugs in.
Each old script's top-level code becomes a function that takes `profile`.

---

## 9. tests

`conftest.py`:

```python
import pytest


@pytest.fixture
def fdus_rate_strings():
    return [
        "SOFR + 7.75%, 2.00% floor, 11.71% cash / 0.50% PIK",
        "SOFR + 6.50%, 1.00% floor",
        "12.00% cash",
        "-",          # equity row, no rate
        "",
    ]
```

`test_rate_parser.py` — these run offline, no API key needed:

```python
from bdc_parser.ai.rate_parser import parse_rate, parse_rate_regex


def test_full_floating_rate():
    rt = parse_rate_regex("SOFR + 7.75%, 2.00% floor, 11.71% cash / 0.50% PIK")
    assert rt.reference == "SOFR"
    assert rt.spread_pct == 7.75
    assert rt.floor_pct == 2.00
    assert rt.cash_pct == 11.71
    assert rt.pik_pct == 0.50


def test_fixed_rate():
    rt = parse_rate_regex("12.00% cash")
    assert rt.cash_pct == 12.00
    assert rt.reference is None


def test_equity_row_empty():
    rt = parse_rate("-")
    assert rt.parsed_by == "none"


def test_regex_only_when_no_llm():
    # _looks_incomplete is False here, so no LLM call regardless of key
    rt = parse_rate("SOFR + 7.75%, 11.71% cash", use_llm=True)
    assert rt.parsed_by == "regex"
```

For `test_parse.py` / `test_profiles.py`: put 2-3 trimmed real HTML table rows
from the FDUS filing into `tests/fixtures/`, then assert the parser produces the
expected `Investment` objects. This is the highest-credibility test set —
it proves the 241-row result is reproducible.

---

## 10. .github/workflows/ci.yml

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest -v -m "not llm"
```

CI never calls a live LLM. Add the badge to the top of the README.

---

## 11. README changes

- Title: "BDC Portfolio Parser" (drop the FDUS-only framing).
- Add CI badge + a "Tested: N passing" line near the top.
- New "Install" section: `pip install -e ".[anthropic]"` (or `.[openai]`).
- New "CLI" section with the `bdc-parse` examples.
- New "AI-assisted rate parsing" section: explain regex-first / LLM-fallback,
  and that the LLM is optional. State plainly that the package runs with no
  API key — this is a feature, not a limitation.
- Keep the FDUS deep-dive content as the worked example.

---

## 12. Suggested commit sequence

The current repo has only 1 commit, which reads as "thrown together for one
job." Commit in stages so the history shows engineering process:

1. `chore: scaffold package layout (pyproject, src/bdc_parser)`
2. `refactor: migrate scripts into bdc_parser modules`
3. `feat: BDCProfile abstraction + FDUS/MAIN/ARCC profiles`
4. `feat: provider-agnostic LLM-assisted rate parser (regex-first fallback)`
5. `test: rate parser + profile + parse fixtures`
6. `ci: add GitHub Actions workflow`
7. `docs: rewrite README for multi-BDC + CLI + AI layer`

Then cut a `v1.0.0` release/tag.

---

## 13. Open items to confirm while coding

- Exact literal column-header strings in the FDUS HTML (for `fdus.yaml`).
- The MAIN / ARCC profiles are stubs — they need real header text before they
  actually parse. Ship them clearly marked as "untuned" or leave them out of
  the v1.0.0 README claims until verified. Do not claim multi-BDC support that
  hasn't been run against a real MAIN/ARCC filing.
- Latest exact `langchain` version + confirm `init_chat_model` import path.
