# CLAUDE.md — FDUS Sample Deliverable

Guidance for Claude Code working in this repository. Project context lives in
`README.md` and `methodology.md`; this file documents working conventions only.

## Project Structure

```
fdus-sample/
├── README.md                  # client-facing summary + top-10 + deep dive
├── methodology.md             # technical write-up, one section per script
├── fdus_sample_presentation.html  # rendered single-page deliverable
├── src/                       # 7 standalone scripts, run in pipeline order
│   ├── fetch_filing.py            # 1. EDGAR fetch → raw/ cache
│   ├── locate_schedule.py         # 2. find Schedule tables in HTML
│   ├── parse_schedule.py          # 3. parse 241 rows → fdus_schedule_full.csv
│   ├── rank_top_companies.py      # 4. aggregate + rank → fdus_top10_*.csv
│   ├── extract_company_filing_data.py  # 5. deep-dive filing extract
│   ├── scrape_company_website.py       # 6. polite requests + BS4 scrape
│   └── finalize_execs.py          # 7. rank execs, emit CSV + JSON
├── data/                      # all generated outputs (CSV + JSON), checked in
├── raw/                       # cached EDGAR HTML, .gitignored (16.9MB)
├── venv/                      # local Python 3 env, .gitignored
└── .claude/settings.local.json # tool-permission allowlist (tracked on purpose)
```

There is no `tests/` directory. Validation is done by sanity-check totals
(see `methodology.md` §3 — parsed fair-value sum reconciles to the filing's
audited Total Investments line, $1,324,753K).

## Workflow Conventions

- **Scripts are standalone**, not a package. Each declares its own `PROJECT_ROOT`
  via `Path(__file__).resolve().parent.parent` and reads/writes paths off that.
  No relative imports between scripts.
- **Run from project root** using the venv interpreter:
  `./venv/Scripts/python.exe src/<script>.py`. The `.claude/settings.local.json`
  allowlist is keyed to that exact invocation.
- **Pipeline order matters** — `fetch_filing.py` must populate `raw/` before
  `parse_schedule.py` runs. `data/` outputs are checked in so downstream scripts
  can be re-run without re-fetching.
- **Outputs are deterministic**. Re-running a script overwrites its CSV/JSON in
  place; diff the working tree to see what changed.
- **External calls are polite**: EDGAR access goes through edgartools (handles
  rate limits + UA); website scraping uses a 1.5s delay and a custom UA string.

## Claude Code Usage

Claude Code drove most of the build. Patterns to keep using:

- Heuristic-first parsing — table detection, row classification, and footnote
  stripping were iterated by inspecting failing rows, not by writing tests
  upfront. Sanity-check totals against the filing's own subtotals are the
  acceptance criterion.
- Tool permissions are pinned per-script in `.claude/settings.local.json` so
  the pipeline replays without prompting. Add a new entry when introducing a
  new script rather than broadening to a wildcard.
- One-off introspection (e.g. `python -c "import json; ..."`) is allowlisted
  with arguments narrowed; prefer narrow allowlist entries over `python -c *`.

## Pytest / Lint / Commit Conventions

- **Pytest**: not configured. If introducing tests, add `pytest` to the venv
  and create `tests/` at the repo root with files mirroring `src/` names.
- **Lint/format**: not configured. Existing code is plain stdlib + `requests`
  + `beautifulsoup4` + `edgartools`, formatted ad hoc. If adding a formatter,
  prefer `ruff` over `black`+`flake8` to keep tooling minimal.
- **Commits**: single-sentence subject describing the artifact and the
  validation, e.g. `FDUS 10-K Schedule of Investments parser — 241 rows,
  103 companies, sanity-checked against audited balance sheet`. No body
  unless the change is non-obvious. No Conventional Commits prefixes.
- **What not to commit**: `raw/` (large, reproducible), `venv/`, `.env`, any
  raw `*.html`. The `.gitignore` enforces this.
- **What to commit**: everything in `src/`, `data/`, the two markdown files,
  the rendered HTML deliverable, and `.claude/settings.local.json`.
