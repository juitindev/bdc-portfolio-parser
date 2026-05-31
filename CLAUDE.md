# CLAUDE.md — BDC Portfolio Parser

Guidance for Claude Code working in this repository. Project context lives in
`README.md`, `methodology.md`, and `ROADMAP.md`; this file documents working
conventions and the scope contract per release. Treat it as authoritative —
when README and CLAUDE.md disagree, fix the README.

## Project Identity

SEC EDGAR BDC (Business Development Company) 10-K parser plus a hybrid
SQL+RAG question-answering layer (v0 in progress). Multi-BDC by design — each
BDC is a YAML profile under `src/bdc_parser/profiles/`. The parser produces
structured CSVs for tabular queries; the QA layer routes natural-language
questions to SQL (numeric/aggregation), RAG (narrative), or a hybrid
composition, with the router's decision visible in CLI output.

## Project Structure

```
bdc-portfolio-parser/
├── README.md                  # user-facing summary + install + demo queries
├── methodology.md             # technical write-up
├── ROADMAP.md                 # deferred work (ARCC v1, non-accrual, etc.)
├── CLAUDE.md                  # this file — agent contract
├── pyproject.toml             # single source of truth for deps + extras
├── Dockerfile                 # CLI image; future qa/ adds a second service
├── docker-compose.yml
├── .env.example
├── .github/workflows/ci.yml
├── src/bdc_parser/            # the package — installed as `bdc-parse` CLI
│   ├── cli.py                     # argparse entry point
│   ├── models.py                  # Pydantic: Investment, RateTerms, BDCProfile
│   ├── paths.py                   # path helpers, ticker-derived
│   ├── fetch.py                   # EDGAR fetch → raw/ cache
│   ├── locate.py                  # find Schedule of Investments tables
│   ├── parse.py                   # parse Schedule rows → schedule_full.csv
│   ├── rank.py                    # aggregate + rank → top10_by_fair_value.csv
│   ├── deepdive.py                # per-company filing extract (see DEPRECATION)
│   ├── website.py                 # polite portfolio-company website scrape
│   ├── execs.py                   # rank execs from scraped website
│   ├── validate.py                # (v0) post-parse validator — profile-agnostic
│   ├── ai/
│   │   ├── llm.py                 # provider-agnostic langchain factory
│   │   └── rate_parser.py         # regex-first, LLM-fallback rate extractor
│   ├── profiles/
│   │   ├── __init__.py            # load_profile(ticker) -> BDCProfile
│   │   ├── fdus.yaml              # FY2025 — canonical sample
│   │   ├── main.yaml              # (v0 in progress)
│   │   └── gain.yaml              # (v0 in progress)
│   └── qa/                        # (v0) hybrid SQL+RAG layer — see Architecture
├── eval/                      # (v0) gold-set eval harness, not pytest
│   ├── questions.yaml
│   ├── judge_prompt.md
│   ├── run_eval.py
│   └── snapshots/                 # checked-in regression baselines
├── tests/                     # pytest, 46 offline tests, sub-second
├── data/                      # generated CSV + JSON, checked in as samples
├── raw/                       # cached EDGAR HTML, gitignored
└── .claude/settings.local.json    # tool-permission allowlist, tracked on purpose
```

## v0 BDC Roster

| Ticker | Status | Notes |
|---|---|---|
| FDUS | shipped | FY2025, 241 rows, sanity-checked against audited Total Investments |
| MAIN | _(planned, not yet implemented)_ | reports in actual dollars (not $K); see units handling |
| GAIN | _(planned, not yet implemented)_ | FDUS-style schedule, expected smooth path |
| ARCC | **deferred to v1** | numbered footnotes + bare-spread rate format + larger schedule; full complexity analysis in `ROADMAP.md` §1 |

When adding a new ticker: write the YAML profile, run `bdc-parse locate <T>`
to confirm header detection, then `bdc-parse schedule <T>
--allow-validation-failure` and work the validator's report as a punch list.

## Forbidden-Until-v1 Capabilities

These queries look impressive but the architecture currently answers them
poorly. Do NOT advertise them in the README, demo set, or eval harness until
the listed dependency lands.

| Capability | Why deferred | v1 dependency |
|---|---|---|
| Non-accrual rate per BDC | `parse.strip_footnotes` (`parse.py:62-70`) currently removes the footnote markers that flag non-accrual status. Field doesn't exist in the CSV. | Footnote-preservation refactor + footnote-legend parser — `ROADMAP.md` §3. |
| Year-over-year change ("how did X's strategy evolve") | `paths.cache_path()` is `{ticker}_10k_latest.html`; no year dimension. Only one filing per BDC indexed. | Multi-year filing support — `ROADMAP.md` §3. |
| Cross-BDC PIK / yield comparisons | Rate-parser regex misses ~10% of rows on FDUS; LLM fallback fills the gap only when an API key is set. Cross-BDC averages aggregate the noise. | Rate-parser hardening across all profiles + mandatory LLM fallback in qa/ paths. |
| "Which company has highest PIK rate" | Same root cause as above plus PIK is sparse — many rows have null PIK and the answer would silently skip them. | Same as above. |

If a user asks a forbidden-list question, answer plainly: the capability is
v1, with a one-line reason. Do not paper over with a partial answer.

## Architecture — Hybrid SQL+RAG (v0)

**STATUS: Only the RAG retrieval + cited-answer path is implemented
(`qa/retrieve.py`, `qa/answer.py`). SQL router, hybrid composition, and the
eval harness are designed but NOT yet built.** The diagram below is the
target architecture; lines marked _(planned, not yet implemented)_ do not
exist as code today.

```
   user question
        │
        ▼
   qa/router.py ──── classifies as: sql | rag | hybrid   (planned, not yet implemented)
        │
   ┌────┴────┐
   ▼         ▼
qa/sql_   qa/retrieve.py
tools.py     │       (qa/sql_tools.py: planned, not yet implemented)
   │         ▼   (Qdrant + BGE-base, indexed from raw/ HTML
   │         │    excluding Schedule of Investments tables)
   ▼         ▼
        qa/answer.py ──── Anthropic Claude, citations required for RAG/hybrid
              │
              ▼
      CLI output (router decision shown by default)
```

- **SQL side** _(planned, not yet implemented)_ runs DuckDB queries directly
  over `data/*_schedule_full.csv` and `data/*_top10_by_fair_value.csv`. No
  Postgres in v0. Templated queries exposed as tool calls (top-N,
  sum-by-category, count-by-type, filter-by-industry).
- **RAG side** uses sentence-transformers `BAAI/bge-base-en-v1.5` (768-dim) into
  Qdrant. Section-aware chunking by 10-K Item header, then ~512 tokens with
  ~64 overlap on paragraph boundaries. Schedule of Investments tables are
  **excluded** from the corpus — they're already structured in CSV.
- **Hybrid** _(planned, not yet implemented)_ composes SQL results into the
  prompt alongside retrieved chunks. Justified only when the answer requires
  both — see eval rubric for the hybrid demo query (the `eval/` harness is
  itself planned, not yet implemented).

**Route + citation output is a feature, not debug noise — do not suppress.**
`bdc-parse ask` shows the route decision (`[route: rag]`) and chunk citations
**by default**. `--quiet` suppresses them. There is no `--verbose` flag — the
verbose form IS the default, on purpose: reviewers see the architecture
working without passing any flag.

## Evaluation Principles

Hybrid-route answers must fail the redaction test in both directions:
removing SQL-derived facts and removing RAG-cited passages must each leave
the answer incomplete. If either redaction leaves the answer intact, the
hybrid route did no real work — re-classify the question or cut hybrid
from v0 per `ROADMAP.md` §2.

## Deprecation Plan

`src/bdc_parser/deepdive.py:32-91` (`find_other_mentions`) is a regex-based
positional retriever — proto-RAG that predates the qa/ layer. Once
`qa/retrieve.py` ships:

1. `deepdive.find_other_mentions` is replaced by a thin call into
   `qa.retrieve.retrieve(query=company_name, ticker=ticker, k=10)`.
2. The `bdc-parse deepdive` CLI command stays; the underlying retrieval is
   shared with `bdc-parse ask`.
3. The heuristic section-labeling in `deepdive.py:62-78` becomes dead code —
   delete it, don't carry both retrieval implementations.

Do not leave both retrievers shipped in parallel.

## Workflow Conventions

- **Package, not scripts.** `pip install -e .` exposes the `bdc-parse` CLI.
  All commands route through `src/bdc_parser/cli.py`. Run from project root
  with the venv interpreter (`.\venv\Scripts\python.exe -m bdc_parser.cli ...`
  or `bdc-parse ...` once installed).
- **Pipeline order matters.** `fetch` must populate `raw/` before `schedule`
  runs. `data/` outputs are checked in so downstream commands can be re-run
  without re-fetching. `raw/` is gitignored.
- **Outputs are deterministic.** Re-running a command overwrites its CSV/JSON
  in place; diff the working tree to see what changed.
- **External calls are polite.** EDGAR access goes through `edgartools`
  (handles rate limits + UA); website scraping uses a 1.5s delay and a custom
  UA string.
- **Profile additions trigger a regression check.** Every parser change must
  leave FDUS's CSV byte-identical (it's the canonical golden output) and
  every existing v0 ticker's CSV passing validation.

## Claude Code Usage

Patterns to keep using:

- **Heuristic-first parsing.** Row classification, footnote stripping, and
  rate extraction are iterated by inspecting failing rows and the validator's
  report — not by writing tests upfront. Sanity-check totals + the validator
  are the acceptance criteria.
- **Tool permissions are pinned per command** in `.claude/settings.local.json`
  so pipelines replay without prompting. Add a narrow entry when introducing
  a new subcommand rather than broadening to a wildcard.
- **Regex first, LLM as fallback.** The package works with no API key; LLM is
  invoked only when the regex result is incomplete. Preserve this property in
  any new module — including qa/, which should refuse rather than hallucinate
  when retrieval is empty.

## Pytest / Lint / Commit Conventions

- **Pytest** is configured (see `pyproject.toml [tool.pytest.ini_options]`).
  Tests live in `tests/`, mirror `src/bdc_parser/` filenames. 46 offline
  tests, sub-second. One opt-in live test is marked `@pytest.mark.llm` and
  skipped unless an API key is set. Add validator and qa/ tests in the same
  pattern — offline by default.
- **Lint/format**: not configured. If introducing tools, prefer `ruff` over
  `black`+`flake8` to keep tooling minimal.
- **Commits**: short subject under ~70 chars. Recent commits use
  Conventional-style prefixes (`docs:` / `feat:` / `fix:`); older
  milestone commits use an artifact-and-validation form
  (`FDUS 10-K Schedule of Investments parser — 241 rows, sanity-checked
  against audited balance sheet`). Both are acceptable. No body unless
  the change is non-obvious. **No AI attribution or co-author tags.**
- **What not to commit**: `raw/` (large, reproducible), `venv/`, `.env`,
  `eval/results/` (timestamped run outputs), any raw `*.html`. The
  `.gitignore` enforces most of this.
- **What to commit**: everything in `src/`, `data/`, `tests/`, `eval/` (except
  `results/`), the markdown files, the rendered HTML deliverable, and
  `.claude/settings.local.json`.
