"""Reproduce all results from raw data (python -m scripts.run_all). See airq.pipelines.run_all."""

from __future__ import annotations

import argparse
import sys

from airq.pipelines.run_all import ok, run_all, stages


def main() -> int:
    names = [s.name for s in stages()]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", help="fresh working directory (AIRQ_HOME); keeps committed results")
    ap.add_argument("--quick", action="store_true", help="2 stations, no Optuna (needs --home)")
    ap.add_argument("--with-system", action="store_true", help="also RQ3a benchmark + scenarios")
    ap.add_argument("--check", action="store_true", help="only verify that outputs exist")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--force", action="store_true", help="re-run stages even if outputs exist")
    ap.add_argument("--skip", nargs="*", default=[], choices=names)
    ap.add_argument("--only", nargs="*", default=[], choices=names)
    ap.add_argument("--keep-going", action="store_true", help="continue after a failed stage")
    args = ap.parse_args()
    results = run_all(
        home=args.home, quick=args.quick, with_system=args.with_system, force=args.force,
        check_only=args.check, dry_run=args.dry_run, skip=set(args.skip),
        only=set(args.only) or None, keep_going=args.keep_going,
    )  # fmt: skip
    good = ok(results)
    print("ALL OUTPUTS PRESENT" if good else "SOME STAGES FAILED OR OUTPUTS ARE MISSING")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
