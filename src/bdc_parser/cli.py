"""bdc-parse command-line interface (stub — wired in Phase 4)."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bdc-parse", description="BDC 10-K parser")
    p.add_argument("--version", action="store_true")
    args = p.parse_args(argv)
    if args.version:
        from bdc_parser import __version__
        print(__version__)
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
