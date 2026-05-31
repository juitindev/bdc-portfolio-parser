"""bdc-parse command-line interface."""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

from bdc_parser import __version__
from bdc_parser.profiles import load_profile, available_profiles

# Load .env from cwd before anything else reads os.environ.
# override=False so an already-set shell env var wins over .env.
load_dotenv(override=False)


def _add_ticker(p):
    p.add_argument("ticker", help="BDC ticker (e.g., FDUS)")


def cmd_profiles(args) -> int:
    profiles = available_profiles()
    print("Available BDC profiles:")
    for t in profiles:
        try:
            prof = load_profile(t)
            print(f"  {t:<6} {prof.name} (CIK {prof.cik})")
        except Exception as e:
            print(f"  {t:<6} ERROR: {e}")
    return 0


def cmd_fetch(args) -> int:
    from bdc_parser.fetch import run
    profile = load_profile(args.ticker)
    run(profile, force=args.force)
    return 0


def cmd_locate(args) -> int:
    from bdc_parser.locate import run
    profile = load_profile(args.ticker)
    run(profile)
    return 0


def cmd_schedule(args) -> int:
    from bdc_parser.parse import run
    profile = load_profile(args.ticker)
    out = run(
        profile,
        use_llm=not args.no_llm,
        allow_validation_failure=args.allow_validation_failure,
    )
    return 0 if out else 1


def cmd_rank(args) -> int:
    from bdc_parser.rank import run
    profile = load_profile(args.ticker)
    run(profile, top=args.top)
    return 0


def cmd_deepdive(args) -> int:
    from bdc_parser.deepdive import run
    profile = load_profile(args.ticker)
    out = run(profile, target=args.target)
    return 0 if out else 1


def _parse_product_urls(raw: str | None) -> list[tuple[str, str, str]]:
    if not raw:
        return []
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    extras = []
    for u in urls:
        path = urlparse(u).path.strip("/")
        label = path.split("/")[-1] if path else u
        extras.append((u, "products", label))
    return extras


def cmd_website(args) -> int:
    from bdc_parser.website import run
    extras = _parse_product_urls(args.product_urls)
    run(
        target=args.target,
        base_url=args.url,
        company_name=args.company_name,
        extra_urls=extras or None,
    )
    return 0


def cmd_execs(args) -> int:
    from bdc_parser.execs import run
    run(target=args.target, top=args.top)
    return 0


def cmd_ask(args) -> int:
    # TODO(v0-router): the next slice is qa/router.py — classify the question
    # as sql | rag | hybrid and dispatch accordingly (SQL over DuckDB, RAG via
    # this path, or a hybrid composition). For today `ask` goes STRAIGHT to the
    # RAG path; there is no router/SQL/hybrid branch yet.
    from bdc_parser.qa.answer import answer

    ticker = args.ticker
    try:
        result = answer(args.question, ticker=ticker, k=args.k,
                        use_llm=not args.no_llm)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    # Verbose chunk citations are shown BY DEFAULT — the router/RAG decision
    # being visible is a documented feature (CLAUDE.md), not debug noise.
    verbose = not args.quiet
    if verbose:
        print(f"[route: rag]  ticker={ticker.upper()}  retrieved={len(result.chunks)} chunk(s)")
        if result.refused:
            print("[route: rag]  retrieval empty -> REFUSING (no grounded source)")
        for i, c in enumerate(result.chunks, 1):
            preview = c.text.strip().replace("\n", " ")
            if len(preview) > 100:
                preview = preview[:100] + "…"
            print(f"  [{i}] score={c.score:.3f}  {c.ref.cite()}")
            print(f"       {preview}")
        print("-" * 80)

    print(result.text)
    return 0 if not result.refused else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bdc-parse", description="BDC 10-K parser")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("profiles", help="list available BDC profiles")

    sp = sub.add_parser("fetch", help="fetch + cache a BDC 10-K from EDGAR")
    _add_ticker(sp)
    sp.add_argument("--force", action="store_true", help="re-fetch even if cached")

    sp = sub.add_parser("locate", help="diagnose Schedule of Investments tables")
    _add_ticker(sp)

    sp = sub.add_parser("schedule", help="parse the Schedule of Investments to CSV")
    _add_ticker(sp)
    sp.add_argument("--no-llm", action="store_true",
                    help="disable LLM rate-parsing fallback (regex-only)")
    sp.add_argument("--allow-validation-failure", action="store_true",
                    help="exit 0 even if post-parse validation fails "
                         "(CSV is written either way)")

    sp = sub.add_parser("rank", help="rank portfolio companies by fair value")
    _add_ticker(sp)
    sp.add_argument("--top", type=int, default=10)

    sp = sub.add_parser("deepdive", help="extract filing data for one portfolio company")
    _add_ticker(sp)
    sp.add_argument("--target", required=True,
                    help="company-name substring (e.g., 'inductivehealth')")

    sp = sub.add_parser("website", help="scrape a portfolio company website")
    sp.add_argument("--target", required=True, help="output slug")
    sp.add_argument("--url", required=True, help="company website URL")
    sp.add_argument("--company-name", default=None,
                    help="display name (defaults to scraped <title>)")
    sp.add_argument("--product-urls", default=None,
                    help="comma-separated product page URLs not in nav")

    sp = sub.add_parser("execs", help="rank top executives from the scraped website")
    sp.add_argument("--target", required=True, help="output slug (same as `website`)")
    sp.add_argument("--top", type=int, default=3)

    sp = sub.add_parser("ask", help="ask a natural-language question (RAG over the 10-K)")
    sp.add_argument("question", help="the question to answer from the filing")
    sp.add_argument("--ticker", default="FDUS",
                    help="BDC ticker to query (v0: FDUS only)")
    sp.add_argument("--k", type=int, default=10,
                    help="number of chunks to retrieve")
    sp.add_argument("--no-llm", action="store_true",
                    help="skip the LLM; return the top grounded passage + citations")
    sp.add_argument("--quiet", action="store_true",
                    help="hide retrieved-chunk citations (verbose is the default demo mode)")

    args = p.parse_args(argv)

    dispatch = {
        "profiles": cmd_profiles,
        "fetch": cmd_fetch,
        "locate": cmd_locate,
        "schedule": cmd_schedule,
        "rank": cmd_rank,
        "deepdive": cmd_deepdive,
        "website": cmd_website,
        "execs": cmd_execs,
        "ask": cmd_ask,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
