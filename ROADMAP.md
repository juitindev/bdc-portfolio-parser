# Roadmap — Deferred Work

Items intentionally scoped out of v0. Each entry is a complete brief —
no external context required.

---

## 1. ARCC (Ares Capital) profile support

**Status:** deferred from v0 — v1 candidate.

**Why deferred:** ARCC stress-tests every assumption in `src/bdc_parser/parse.py`
and `src/bdc_parser/ai/rate_parser.py`. Estimated 5–8h of parser work on top
of the v0 budget. v0 ships with FDUS + MAIN + GAIN, which cover the FDUS-style
schedule format. ARCC is structurally different and earns its own milestone.

**Complexity analysis (what changes are required):**

| Concern | Location | Change |
|---|---|---|
| Numbered footnotes `(1)`, `(2)`, `(15)` instead of lowercase `(a)`, `(b)` | `parse.py:62-70` (`strip_footnotes`) | Extend regex `\(([a-z]{1,3})\)` → `\((?:[a-z]{1,3}\|\d{1,2})\)`. Add tests with `(15)` examples. |
| Bare-spread rate format: `"SOFR + 5.75%"` or `"S + 5.75%"` (no surrounding parens) | `rate_parser.py:18` (`_ABBR_SPREAD`) | Add `_BARE_SPREAD` regex as an earlier branch: `\b([SPLB]\|SOFR\|LIBOR\|Prime\|Base Rate)\s*\+\s*([\d.]+)\s*%`. |
| Floor written inline: `"5.75% (1.50% floor)"` | `rate_parser.py:23` (`_PAREN_FLOOR`) | Already partially handled by `_GENERIC_FLOOR` but inline format may also need a third pattern. |
| Possible separate cash/PIK columns instead of `cash/PIK` in one cell | `rate_parser.py:29` (`_CASH_SLASH_PIK`) | Requires `parse.extract_investment_fields` to recognize that some BDCs allocate cash and PIK to separate cells. Currently FDUS-format only. |
| Larger schedule — continuation tables may have adjacency gap > 2 | `locate.py:100` | Bump `if i - current.tables[-1] <= 2` to `<= 4` (or per-profile config). |
| Invest-type vocabulary includes "Senior Direct Lending" / "Senior Secured Loan" / "Junior Capital" without "Lien" keyword | `parse.py:39-43` (`INVEST_TYPE_PATTERNS`) | Broaden to include `Senior Secured\|Senior Direct\|Junior Capital`. Verify no false positives against FDUS/MAIN/GAIN. |
| Header text may split across 3 rows or use slightly different column wording | `locate.py:53-63` (`is_header_table`) | Increase `limit=5` to `limit=8`. Possibly broaden keyword check. |
| Schedule may include extra numeric columns (e.g., "Percentage of Class Held" for equity) that `extract_investment_fields` will misallocate as amounts | `parse.py:114-188` | Hardest change. May need column-aware extraction or a column-skip heuristic based on column position / preceding header. |

**Acceptance criteria for the ARCC milestone:**
1. `bdc-parse schedule ARCC` produces a CSV that reconciles within ±0.5% of
   ARCC's audited Total Investments line in the FY filing.
2. The post-parse validator (see `src/bdc_parser/validate.py` once
   implemented) reports zero errors.
3. None of the v0 BDCs (FDUS/MAIN/GAIN) regress — their CSVs are byte-identical
   to the v0 baseline after the parser changes ship.

**Order of operations when picking this up:**
1. Run `bdc-parse fetch ARCC` (after committing `arcc.yaml`).
2. Run `bdc-parse locate ARCC` and read the diagnostic output. Confirm header
   detection works before touching `parse.py`.
3. Run `bdc-parse schedule ARCC --allow-validation-failure` and use the
   validator's report as a punch list.
4. Fix one validator error class at a time; rerun. Resist generalizing until
   the same fix is needed by a third BDC.

---

## 2. Decision criteria — pre-committed scope cuts

Recorded here so the choice is on the record, not made under pressure
mid-implementation.

### Hybrid route — kill criterion

If, during qa/ implementation, the hybrid demo query (Q6 — "FDUS top 5
industries by fair value + risk-factor disclosure on industry
concentration") cannot satisfy the redaction test in both directions —
i.e., either the SQL-derived facts or the RAG-cited passages can be
removed without leaving the answer incomplete — drop the hybrid route
from v0 entirely.

Ship v0 with five queries (three SQL, two RAG) and move hybrid to v1.
Rationale: a clean SQL+RAG demo is stronger than a muddy
SQL+RAG+hybrid one where the router occasionally fires "hybrid" but
reviewers can't see why. The redaction test is the gate.

This decision is taken once, at `qa/answer.py` + `eval/run_eval.py`
implementation time. If hybrid passes once cleanly on Q6, it stays in
v0; if it fails, it's cut without renegotiation.

## 3. Other v1 candidates (one-line stubs — flesh out when scheduled)

- **Footnote-flag extraction for non-accrual / PIK / unfunded** — requires
  preserving the footnote letters that `parse.strip_footnotes` currently
  removes, plus parsing the footnote legend at the end of each Schedule.
  Unlocks the "which BDC has the highest non-accrual rate" SQL query.
- **pgvector + Postgres migration** — collapse DuckDB-over-CSV + Qdrant into
  one engine. Worth it once cross-BDC SQL+vector queries become routine.
- **Reranker (`bge-reranker-base`)** — easy retrieval-quality bump for
  qa/retrieve.py once the v0 retrieval path is stable.
- **FastAPI shell** — dropped from v0 for budget reasons; CLI is enough for
  the demo. Add when the demo needs a web surface.
- **Eval harness expansion** — v0 ships a ~20-question gold set. v1 grows
  it with edge cases discovered during use, and adds retrieval-precision
  metrics on top of the LLM-as-judge answer scoring.
- **Multi-year filings** — currently `paths.cache_path()` is
  `{ticker}_10k_latest.html` with no year dimension. Unlocks "how did
  Main Street's strategy change between 2023 and 2024."
