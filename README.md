# BDC Portfolio Parser

[![CI](https://github.com/juitindev/bdc-portfolio-parser/actions/workflows/ci.yml/badge.svg)](https://github.com/juitindev/bdc-portfolio-parser/actions/workflows/ci.yml)

Parse SEC EDGAR Business Development Company (BDC) 10-K filings into structured portfolio data. Lifts the Schedule of Investments out of HTML tables, ranks portfolio companies by aggregate fair value, and runs deep-dive extraction on a single company (filing mentions, website scrape, executive ranking).

- **Regex-first rate parsing.** Structured `RateTerms` (reference, spread, floor, cash, PIK) are extracted by pattern matching. The package works with no API key. An LLM is invoked only as a fallback when the regex result is incomplete and a provider key is present.
- **Provider-agnostic.** Anthropic, OpenAI, Google — switch with one env var.
- **One BDC per profile.** Adding a new BDC is a YAML file with ticker, name, and CIK. Parsing is generic; the section labels (Control / Affiliate / Non-control) come from the Investment Company Act and apply to every BDC.
- **Tested.** 46 offline unit tests, sub-second runtime.

A worked example using Fidus Investment Corp's FY2025 10-K is included in `data/` — 241 investment rows, 103 portfolio companies, $1,324,753K total fair value, reconciled to the audited Total Investments line.

## Install

```bash
git clone https://github.com/juitindev/bdc-portfolio-parser.git
cd bdc-portfolio-parser
python -m venv venv
./venv/Scripts/python -m pip install -e ".[dev]"          # Windows
# source venv/bin/activate && pip install -e ".[dev]"      # macOS / Linux
```

LLM extras are optional and chosen by provider:

```bash
pip install -e ".[anthropic]"   # or .[openai]
export ANTHROPIC_API_KEY=sk-ant-...
```

With no extras and no key, every rate string is still parsed by the regex layer.

## CLI

```bash
bdc-parse profiles                                          # list available BDCs
bdc-parse fetch FDUS                                        # download + cache 10-K
bdc-parse locate FDUS                                       # diagnose Schedule tables
bdc-parse schedule FDUS                                     # parse Schedule -> CSV
bdc-parse schedule FDUS --no-llm                            # regex-only run
bdc-parse rank FDUS --top 10                                # aggregate by company
bdc-parse deepdive FDUS --target inductivehealth            # one portfolio company
bdc-parse website --target inductivehealth \
    --url https://inductivehealth.com/                      # polite site scrape
bdc-parse execs --target inductivehealth                    # rank executives
```

Outputs land in `data/`, named after the ticker / target slug. Raw HTML is cached in `raw/` (gitignored).

## Adding a new BDC

Create `src/bdc_parser/profiles/<ticker>.yaml`:

```yaml
ticker: MAIN
name: Main Street Capital Corporation
cik: "0001396440"
notes: >
  Optional notes — filing context, parsing quirks, etc.
```

That's the whole profile. Parsing is content-pattern-driven, so column header strings are not required — the parser detects investment-type keywords, dates, rates, and amounts by shape regardless of column order.

## AI-assisted rate parsing

The parser produces structured rate terms for every debt row. The flow is:

1. **Regex pattern matching** runs unconditionally. It handles FDUS-style two-cell rates (`(S+7.75%) / (2.00%)` + `11.71%/0.50%`), generic keyword forms (`SOFR + 7.75%, 2.00% floor`), and fixed rates (`12.00%`).
2. **LLM fallback** runs only if (a) the regex result is missing both a floating-rate identifier and a cash rate, (b) `langchain` is installed, (c) a provider API key is set, and (d) `--no-llm` was not passed. The LLM uses Pydantic structured output so its result lands in the same `RateTerms` shape.
3. **No LLM, no problem.** With no extras installed and no key set, parsing returns the regex result. On the FDUS sample, 111/111 debt rows are parsed without invoking any LLM.

Output CSV adds 6 columns to the legacy schema: `rate_reference`, `rate_spread_pct`, `rate_floor_pct`, `rate_cash_pct`, `rate_pik_pct`, `rate_parsed_by` (`regex` | `llm` | `none`). The 11 legacy columns are preserved unchanged.

Override the default model with `BDC_PARSER_MODEL`, e.g. `anthropic:claude-haiku-4-5` or `openai:gpt-4o-mini`.

## Worked example — Fidus Investment Corp (FDUS) FY2025

CIK 0001513363. Filing accession 0001193125-26-076572, filed 2026-02-26. 16.9MB raw HTML, 158 `<table>` elements, Schedule of Investments split across tables #79–#83 (auto-detected).

### Top 10 by total fair value

| Rank | Company | FV ($K) | # Inv | Investment Types |
|------|---------|--------:|------:|-----------------|
| 1 | Pfanstiehl, Inc. | 40,995 | 1 | Common Equity |
| 2 | InductiveHealth Informatics, LLC | 38,389 | 4 | Common Equity; First Lien Debt; Preferred Equity |
| 3 | Fishbowl Solutions, LLC | 35,063 | 3 | First Lien Debt; Revolving Loan |
| 4 | American AllWaste LLC (dba WasteWater Transport Services) | 33,944 | 10 | Common Equity; First Lien Debt; Preferred Equity |
| 5 | GMP HVAC, LLC (dba McGee Heating & Air, LLC) | 31,350 | 2 | First Lien Debt; Preferred Equity |
| 6 | Spectra A&D Acquisition, Inc. | 31,197 | 6 | Common Equity; First Lien Debt |
| 7 | Detechtion Holdings, LLC | 31,061 | 4 | Common Equity; First Lien Debt; Revolving Loan; Subordinated Debt |
| 8 | Barefoot Mosquito and Pest Control, LLC | 30,913 | 4 | Common Equity; First Lien Debt; Preferred Equity |
| 9 | ServicePower, Inc. | 30,038 | 2 | First Lien Debt |
| 10 | Dealerbuilt Acquisition, LLC | 27,310 | 4 | Common Equity; First Lien Debt; Preferred Equity; Subordinated Debt |

Top 10 = $330,260K (24.9% of portfolio). Source: `data/fdus_top10_by_fair_value.csv`.

### Deep dive: InductiveHealth Informatics (rank #2, $38.4M FV)

Four investment rows across three types (First Lien Debt, Preferred Equity, Common Equity). Non-control/Non-affiliate category. Initial investment 9/20/2024; $3.0M add-on tranche funded 12/16/2025 at the same terms. Aggregate cost $38,031K, fair value $38,389K — slight appreciation, performing at or above par. Debt rate: SOFR + 7.75% with 2.00% floor, yielding 11.71% cash + 0.50% PIK; maturity 9/20/2028. No mentions in MD&A, risk factors, or footnotes (BDCs only flag problem credits in narrative sections).

| # | Type | Rate | Date | Maturity | Principal ($K) | Cost ($K) | FV ($K) |
|---|------|------|------|----------|---------------:|----------:|--------:|
| 1 | First Lien Debt | S+7.75%/2.00% floor, 11.71%/0.50% PIK | 9/20/2024 | 9/20/2028 | 35,065 | 34,775 | 35,065 |
| 2 | First Lien Debt | S+7.75%/2.00% floor, 11.71%/0.50% PIK | 12/16/2025 | 9/20/2028 | 2,993 | 2,964 | 2,994 |
| 3 | Preferred Equity | — | 9/20/2024 | — | — | 292 | 330 |
| 4 | Common Equity | — | 9/20/2024 | — | — | — | — |

**Top 3 executives** (`inductivehealth.com/about-us/`):

| Rank | Name | Title |
|------|------|-------|
| 1 | Eric Whitworth | Chief Executive Officer |
| 2 | Gary Lawrence | Chief Financial Officer |
| 3 | Greg Smith | Chief Information Security Officer |

LinkedIn enrichment deferred pending ToS compliance discussion — Apollo.io or Crunchbase API recommended if scoped.

## Outputs

- `data/fdus_schedule_full.csv` — Schedule of Investments (241 rows × 17 cols)
- `data/fdus_top10_by_fair_value.csv` — top 10 ranked
- `data/inductivehealth_filing_data.json` — all Schedule rows + cross-filing mentions
- `data/inductivehealth_website.json` — 9 scraped pages
- `data/inductivehealth_execs.csv` / `.json` — top 3 executives

## Methodology

Filing retrieval, table detection, row classification, footnote handling, sanity-check reconciliation — see [methodology.md](methodology.md).

## Repository layout

```
src/bdc_parser/
├── cli.py                 # argparse entry point
├── models.py              # BDCProfile (thin), Investment, RateTerms
├── paths.py               # output-path helpers, all keyed off ticker / target
├── fetch.py               # EDGAR retrieval (edgartools)
├── locate.py              # detect Schedule of Investments table groups
├── parse.py               # parse Schedule rows -> CSV
├── rank.py                # aggregate by company, rank by fair value
├── deepdive.py            # filing-side extraction for one company
├── website.py             # polite WordPress / static-HTML scraper
├── execs.py               # rank top executives by title seniority
├── profiles/
│   ├── __init__.py        # load_profile(ticker)
│   └── fdus.yaml
└── ai/
    ├── llm.py             # provider-agnostic init_chat_model factory
    └── rate_parser.py     # regex-first, LLM-fallback
```
