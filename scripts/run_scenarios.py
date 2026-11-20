"""Play the ready-made Senaryo Kontrol scenarios on the real stack.

python -m scripts.run_scenarios [--only NAME ...] [--speedup 7200] [--force] [--list]

Writes reports/scenarios/<name>.json (steps, scorecard, hypothesis verdicts) and
reports/tables/scenarios_summary.csv. Hypotheses in the YAML files are never edited to fit.
Each scenario needs ~4 minutes at the default speed (the predictor warm-up alone is 240 sim hours).
"""

from __future__ import annotations

import argparse
import sys

from airq.config import load_config
from airq.pipelines.scenarios import rescore, run_all
from airq.scenarios.spec import load_all


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="scenario names (default: all)")
    ap.add_argument("--speedup", type=float, default=7200.0, help="simulated hours: 3600 = 1 s/h")
    ap.add_argument(
        "--force", action="store_true", help="re-run scenarios that already have a json"
    )
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--rescore", action="store_true", help="score stored runs again, no re-run")
    ap.add_argument("--dir", default="configs/scenarios")
    args = ap.parse_args()
    if args.list:
        sys.stdout.reconfigure(encoding="utf-8")  # descriptions are Turkish
        for sc in load_all(args.dir).values():
            print(f"{sc.name:22s} {sc.start}  {sc.description}")
        return
    if args.rescore:
        rescore(load_config(), args.only, args.dir)
    else:
        run_all(load_config(), args.only, args.speedup, args.force, args.dir)
    print("summary: reports/tables/scenarios_summary.csv")


if __name__ == "__main__":
    main()
