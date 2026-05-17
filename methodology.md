# Methodology

Technical detail on how data was retrieved, parsed, and validated. Each step corresponds to a module in `src/bdc_parser/`.

## 1. Filing Retrieval (`src/bdc_parser/fetch.py`)

Used [edgartools](https://github.com/dgunning/edgartools) v5.30.0 to fetch the filing via SEC EDGAR's REST API:

```python
Company("FDUS").get_filings(form="10-K")[0].html()
```

This bypasses browser-based scraping entirely. edgartools handles EDGAR rate limiting, user-agent identification, and filing index navigation. The raw HTML (16.9MB) is cached locally in `raw/fdus_10k_latest.html`; subsequent runs load from cache without hitting EDGAR.

Filing: Fidus Investment Corporation 10-K, FY2025, filed 2026-02-26, accession 0001193125-26-076572, CIK 0001513363.

## 2. Locating the Schedule of Investments (`src/bdc_parser/locate.py`)

The 10-K contains 158 HTML `<table>` elements. The Schedule of Investments is not a single table — it is split across 5 consecutive `<table>` elements (tables #79–#83), an artifact of page breaks in the original filing document.

Detection method:
- Scanned all 158 tables for header rows containing "Portfolio Company" AND "Investment Type" (split across two `<tr>` rows — the FDUS filing uses a two-row header)
- Verified candidate tables contain investment-type data (dates in M/D/YYYY format, rate patterns like X.XX%, investment-type keywords)
- Identified 2 Schedule groups: Group 1 (tables #79–#83, FY2025 current year) and Group 2 (tables #84–#87, FY2024 comparative). Only Group 1 was parsed.

Within Group 1, the three Investment Company Act categories appear as inline section labels:
- **Control Investments** — 3 rows (US GreenFiber, LLC)
- **Affiliate Investments** — 19 rows (7 companies including Pfanstiehl, Spectra A&D)
- **Non-control/Non-affiliate Investments** — 219 rows (95 companies)

Section labels were matched longest-first to avoid substring collisions ("control investments" is a substring of "non-control/non-affiliate investments").

## 3. Row Parsing (`src/bdc_parser/parse.py`)

Each `<tr>` in the Schedule was classified as one of:

| Type | Description | Handling |
|------|-------------|----------|
| HEADER | Column header rows ("Portfolio Company", "Investment Type") | Skipped |
| SECTION | Category label ("Control Investments (t)") | Updates current category state |
| COMPANY | Company name + industry (2 non-empty cells) | Updates current company/industry state |
| INVEST | Investment line (First Lien Debt, Equity, etc.) | Parsed → output row |
| SUBTOTAL | Company-level total (no text in first cell, has amounts) | Skipped |
| TOTAL | Section or grand total ("Total Investments") | Skipped |
| EMPTY | Blank row | Skipped |

**241 investment rows** parsed across **103 unique portfolio companies**.

Column structure (mapped to CSV fields):

| Filing Column | CSV Field | Notes |
|---------------|-----------|-------|
| Portfolio Company (a)(b) | company_name | Footnote markers stripped |
| Industry | industry | |
| Variable Index Spread / Floor (d) | rate_spread_floor | Raw string, e.g. "(S+7.75%) / (2.00%)" |
| Rate Cash/PIK | rate_cash_pik | Raw string, e.g. "11.71%/0.50%" |
| Investment Date (f) | investment_date | M/D/YYYY format |
| Maturity | maturity_date | M/D/YYYY format |
| Principal Amount | principal_amount | In thousands, debt only |
| Cost | cost | In thousands |
| Fair Value (g) | fair_value | In thousands |

Cleaning steps:
- **Footnote markers**: Stripped trailing markers like `(a)`, `(am)`, `(h)(j)` from company names and investment types. Preserved `(dba XYZ)` alternate names (e.g., "GMP HVAC, LLC (dba McGee Heating & Air, LLC)").
- **Unit/share info**: Stripped from investment types (e.g., "Common Equity (1,000units)" → "Common Equity").
- **Accounting negatives**: Parsed parenthesized values as negatives. In SEC filings, `(14)` means `-14`. The closing `)` sometimes lands in a separate `<td>` cell — handled by a look-ahead merge.
- **Null values**: `—` (em dash) and `$—` treated as null, not zero. These represent unfunded commitments, nominal equity kickers, or positions with no assigned fair value.
- **Dollar signs**: `$` characters occupy their own `<td>` cells in the HTML — filtered during field extraction.
- **Company names starting with digits**: Handled (e.g., "2KDirect, Inc.", "301 Edison Holdings Inc.").

**Sanity check**: Sum of `fair_value` across all 241 parsed rows = **$1,324,753K**. This matches the filing's "Total Investments" subtotal line exactly. The filing also shows "Total Investments and Money Market Funds" of $1,393,727K, which includes $68,974K in Goldman Sachs money market funds — correctly excluded from our parse (cash equivalents, not portfolio companies).

## 4. Company Aggregation (`src/bdc_parser/rank.py`)

Many portfolio companies have multiple investment rows — a typical BDC capital structure might include First Lien Debt + Revolving Loan + Preferred Equity + Common Equity across separate rows.

Aggregation:
- Grouped all 241 rows by `company_name` (exact match — verified no near-duplicates exist)
- Summed `fair_value` per company
- Sorted descending
- Top 10 companies account for $330,260K = 24.9% of total portfolio fair value (moderate concentration)

One naming note: "Applegate Greenfiber Intermediate Inc." (Affiliate, rank #13) and "US GreenFiber, LLC" (Control, rank #103) are related entities (filing notes "fka US GreenFiber"). They are kept separate because the filing lists them as distinct legal entities in different investment categories.

## 5. Website Scraping — InductiveHealth (`src/bdc_parser/website.py`)

Target: inductivehealth.com (WordPress, server-rendered static HTML).

Scraping stack: `requests` + `BeautifulSoup`. No headless browser required — all content present in raw HTML source.

Pages scraped (9 total, all HTTP 200):

| Page | URL | Size |
|------|-----|-----:|
| Homepage | `/` | 81KB |
| Services | `/services/` | 61KB |
| About Us | `/about-us/` | 67KB |
| Contact | `/contact-us/` | 79KB |
| EDSS | `/inductivehealthedss/` | 69KB |
| EpiTrax | `/epitrax/` | 61KB |
| NBS | `/nbs/` | 62KB |
| WebIZ | `/webiz/` | 68KB |
| ESSENCE | `/essence/` | 64KB |

Polite scraping: 1.5-second delay between requests, custom user-agent (`fdus-sample-research/1.0`).

Executive extraction from `/about-us/`: 6 executives found in structured HTML blocks (WordPress team member pattern — heading element for name, adjacent element for title). Ranked by seniority: CEO > CFO > other C-suite > EVP > SVP > VP. Substring collision handled ("Vice President" does not false-match the "President" tier).

## 6. What's Not Here

- **LinkedIn enrichment**: Deferred. Automated LinkedIn profile scraping violates LinkedIn's Terms of Service. Compliant alternatives: Apollo.io API, Crunchbase API, or manual lookup. Recommend scoping separately.
- **10-Q cross-reference**: The FY2025 10-K covers through 12/31/2025. No subsequent 10-Q has been filed as of this analysis. When available, the Q1 2026 10-Q Schedule of Investments would show any interim changes (new investments, repayments, fair value adjustments).
- **8-K monitoring**: Material events affecting individual portfolio companies (e.g., restructurings, exits, write-downs) surface in 8-K filings. Building a monitoring pipeline for these is separate scope.
- **XBRL fact extraction**: Not needed for Schedule of Investments parsing — the Schedule is embedded as HTML tables, not as structured XBRL facts. edgartools handles XBRL for standard financial statements (balance sheet, income statement) if needed for other analyses.

## 7. Reusability Notes

Parser assumptions that hold across BDCs (per Investment Company Act):
- Three investment categories: Control (>25% voting), Affiliate (5-25%), Non-control/Non-affiliate (<5%). Universal.
- Schedule of Investments is a required disclosure. Always present in 10-K.

Parser assumptions that may vary across BDCs:
- **Column headers**: BDCs use varied header strings — "Par Amount" vs "Principal Amount", optional "Industry" column, "% of Total Investments" vs "% of Net Assets". The parser does not match by header text; it extracts fields by content pattern (dates as `M/D/YYYY`, rates as `X.XX%`, amounts as comma-separated digits, investment-type keywords for the type cell). Column reorderings and renames are absorbed automatically — there is no per-BDC field-mapping configuration to maintain.
- **Table splitting**: The number of HTML `<table>` elements varies by filing preparer. Some BDCs render the entire Schedule as a single table; others split across 5-10 tables. The continuation-detection logic in `find_schedule_groups()` (is_header_table + has_investment_data within 2 table positions) handles this.
- **Footnote conventions**: Marker styles vary (`(a)` vs `(1)` vs `*`). The current regex strips single and double lowercase letter markers. Numeric markers would need a pattern update.
- **Portfolio size**: FDUS has 103 companies / 241 rows. Larger BDCs like ARCC (~500 companies) will have proportionally larger Schedules but the same structure. Not tested at that scale but no structural reason it wouldn't work.
