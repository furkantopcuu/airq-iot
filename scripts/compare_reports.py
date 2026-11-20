"""Does a reproduction give the committed numbers? (python -m scripts.compare_reports)

Compares reports/tables/*.csv (and the metric JSON files) of two reports folders. Timing-dependent
tables (RQ3a, scenarios) are left out unless --include-timing is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from airq.env import resolve_home
from airq.pipelines.compare import compare_json, compare_reports, summarize

METRICS = ["forecast_v1.json", "forecast_test.json", "warning_test.json", "rq3b_test.json",
           "edge_params.json"]  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", type=Path, default=resolve_home() / "reports", help="reference reports/")
    ap.add_argument("--b", type=Path, required=True, help="reproduction reports/")
    ap.add_argument("--rtol", type=float, default=1e-6)
    ap.add_argument("--include-timing", action="store_true")
    args = ap.parse_args()
    diffs = compare_reports(args.a, args.b, args.rtol, include_timing=args.include_timing)
    print(summarize(diffs))
    bad = [d for d in diffs if d.status in ("different", "missing_a", "missing_b")]
    for name in METRICS:
        pa, pb = args.a / "metrics" / name, args.b / "metrics" / name
        if pa.exists() and pb.exists():
            problems = compare_json(pa, pb, args.rtol)
            verdict = "identical within rtol" if not problems else f"{len(problems)} differences"
            print(f"{name}: {verdict}")
            for p in problems[:5]:
                print("    ", p)
            bad += [name] if problems else []
    print("REPRODUCED" if not bad else f"{len(bad)} item(s) differ")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
