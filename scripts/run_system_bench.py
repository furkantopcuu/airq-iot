"""RQ3a system benchmark (python -m scripts.run_system_bench --plan reduced).

Resumable: finished runs are appended to reports/bench/raw_<plan>.csv and skipped next time.
Plans: smoke (one short plumbing run), reduced (about one hour), full (the specified grid).
"""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.pipelines.rq3a import aggregate_bench, plan_runs, run_bench


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=["smoke", "reduced", "full"], default="reduced")
    ap.add_argument("--limit", type=int, default=None, help="run at most N pending runs")
    ap.add_argument(
        "--no-predictor", action="store_true", help="skip the predictor (plumbing tests)"
    )
    ap.add_argument("--sim-days", type=int, default=14)
    ap.add_argument("--aggregate", action="store_true", help="only rebuild rq3a_bench.csv")
    args = ap.parse_args()
    if args.aggregate:
        print(aggregate_bench(load_config(), args.plan).round(3).to_string(index=False))
        return
    print(f"{len(plan_runs(args.plan))} runs in plan '{args.plan}'", flush=True)
    run_bench(load_config(), args.plan, args.limit, not args.no_predictor, args.sim_days)


if __name__ == "__main__":
    main()
