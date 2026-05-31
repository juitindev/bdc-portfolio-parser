# BDC Portfolio Parser

[![CI](https://github.com/juitindev/bdc-portfolio-parser/actions/workflows/ci.yml/badge.svg)](https://github.com/juitindev/bdc-portfolio-parser/actions/workflows/ci.yml)

Parse SEC EDGAR Business Development Company (BDC) 10-K filings into structured portfolio data. Lifts the Schedule of Investments out of HTML tables, ranks portfolio companies by aggregate fair value, and runs deep-dive extraction on a single company (filing mentions, website scrape, executive ranking).

- **Regex-first rate parsing.** Structured `RateTerms` (reference, spread, floor, cash, PIK) are extracted by pattern matching. The package works with no API key. An LLM is invoked only as a fallback when the regex result is incomplete and a provider key is present.
- **Provider-agnostic.** Anthropic, OpenAI, Google — switch with one env var.
- **One BDC per profile.** Adding a new BDC is a YAML file with ticker, name, and CIK. Parsing is generic; the section labels (Control / Affiliate / Non-control) come from the Investment Company Act and apply to every BDC.
- **Tested.** 85 offline unit tests, sub-second runtime.

A worked example using Fidus Investment Corp's FY2025 10-K is included in `data/` — 241 investment rows, 103 portfolio companies, $1,324,753K total fair value, reconciled to the audited Total Investments line.

## Attribution-grounded RAG (FDUS)

`bdc-parse ask "<question>" --ticker FDUS` answers natural-language questions over the 10-K narrative — Item 1 Business, MD&A, risk factors. The Schedule of Investments tables are excluded from the corpus; they're already structured in `data/fdus_schedule_full.csv`. Retrieval uses Qdrant + `BAAI/bge-base-en-v1.5` embeddings with section-aware chunking by 10-K Item header, and XBRL / boilerplate front-matter is filtered out. Every claim in the answer carries an inline citation to a source locator (`[FDUS 10-K | Item N | chars …]`); if retrieval finds nothing relevant, the layer refuses rather than hallucinating. Only the RAG path is built today — there is no SQL routing, hybrid composition, or multi-BDC QA yet.

```bash
bdc-parse ask "What is FDUS's investment strategy?" --ticker FDUS
```

```
[route: rag]  ticker=FDUS  retrieved=10 chunk(s)
  [1] score=0.667  [FDUS 10-K | Item 1 (Business) | chars 330077-333770]
  ...
FDUS provides customized debt and equity financing to lower middle-market
companies with revenues of $10.0M–$150.0M [2][3], primarily through unitranche
or first-lien senior secured loans coupled with an equity interest [1].

Sources:
[1] [FDUS 10-K | Item 1 (Business) | chars 330077-333770]
[2] [FDUS 10-K | Item 7 (Management's Discussion and Analysis ...) | chars 625182-629692]
[3] [FDUS 10-K | Item 1 (Business) | chars 319520-322970]
```

## Install

Three labelled options:

**Core** (parsing only, no LLM):
```bash
pip install -e .
```

**With LLM rate-parsing** (adds langchain + a provider SDK):
```bash
pip install -e ".[anthropic]"      # or .[openai]
```

**For development** (adds pytest for the test suite):
```bash
pip install -e ".[dev]"
```

Extras are additive — combine with a comma, e.g. `pip install -e ".[dev,anthropic]"`. **`[dev]` does NOT include the LLM layer** — install an `[anthropic]` or `[openai]` extra alongside `[dev]` if you want LLM fallback while running tests.

## Configuration

EDGAR requires every request to identify itself with a name + email. Copy the template and edit:

```bash
cp .env.example .env
# then edit .env: set EDGAR_IDENTITY=Your Name your@email.com
```

A placeholder default lives in code (`BDC Portfolio Parser parser@example.com`), but **SEC may rate-limit or block it — set your own real identity before running `bdc-parse fetch`.**

If you installed an LLM extra and want the fallback active, also add a provider key to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
# or OPENAI_API_KEY=...
# or GOOGLE_API_KEY=...
```

`.env` is the cross-platform way to set these. The CLI auto-loads `.env` from the current working directory at startup; a shell-exported variable takes precedence over `.env` if both are set. If you prefer the shell, the equivalents are `export VAR=value` (bash / zsh) or `$env:VAR = "value"` (PowerShell).

## Quickstart

`raw/` is gitignored, so a fresh clone has no cached filing — **`bdc-parse fetch FDUS` MUST run before `schedule` / `rank` / `deepdive`.** Follow these six steps in order:

1. **Clone and create the venv**
   ```bash
   git clone https://github.com/juitindev/bdc-portfolio-parser.git
   cd bdc-portfolio-parser
   python -m venv venv
   ```
   Activate it: `.\venv\Scripts\activate` (Windows PowerShell / cmd), `source venv/Scripts/activate` (Git Bash on Windows), or `source venv/bin/activate` (macOS / Linux).

2. **Install** (see [Install](#install) for the three options):
   ```bash
   pip install -e .
   ```

3. **Configure `.env`** (see [Configuration](#configuration)):
   ```bash
   cp .env.example .env
   # edit .env and set EDGAR_IDENTITY=Your Name your@email.com
   ```

4. **Fetch** the 10-K from EDGAR (~17MB, one-time per filing):
   ```bash
   bdc-parse fetch FDUS
   ```

5. **Parse** the Schedule of Investments:
   ```bash
   bdc-parse schedule FDUS
   ```
   Output: `data/fdus_schedule_full.csv` (241 rows × 17 columns).

6. **Rank** portfolio companies by aggregate fair value:
   ```bash
   bdc-parse rank FDUS
   ```
   Output: `data/fdus_top10_by_fair_value.csv`.

Optional deep-dive on one portfolio company:

```bash
bdc-parse deepdive FDUS --target inductivehealth
bdc-parse website --target inductivehealth --url https://inductivehealth.com/
bdc-parse execs --target inductivehealth
```

End-to-end (steps 4–6) takes ~30s on a warm cache. Subsequent runs read from `raw/<ticker>_10k_latest.html` without re-hitting EDGAR.

## CLI reference

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

## Run with Docker

Same pipeline, no local Python needed. The image bakes in the LLM extra so regex-first / LLM-fallback both work as soon as you supply an API key.

**Build:**
```bash
docker compose build
```

**Configure `.env` first** (same as the native install — see [Configuration](#configuration)):
```bash
cp .env.example .env
# edit .env: set EDGAR_IDENTITY=Your Name your@email.com
# optionally set ANTHROPIC_API_KEY=...
```

`.env` is loaded by compose at runtime via `env_file`. Secrets are never baked into the image.

**Run** — same subcommands as native, just prefixed:

Regex-only run (no API key needed):
```bash
docker compose run --rm bdc-parse fetch FDUS
docker compose run --rm bdc-parse schedule FDUS --no-llm
docker compose run --rm bdc-parse rank FDUS
```

With LLM fallback active (requires `ANTHROPIC_API_KEY` in `.env`):
```bash
docker compose run --rm bdc-parse schedule FDUS
```

The compose service bind-mounts `./raw` and `./data` from the host, so fetched filings and pipeline outputs persist between container runs. `bdc-parse fetch FDUS` is still one-time per filing.

> **Note:** `requirements.txt` just points at `pyproject.toml` (`-e .`). It exists for users who look for it; the actual dependency list lives in `pyproject.toml`.

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
