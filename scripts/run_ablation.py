"""Optuna tuning + neighbor ablation on validation (python -m scripts.run_ablation).

Resumable: the Optuna studies live in models/optuna.db, so an interrupted run continues.
"""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.pipelines.tuning import run_tuning


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2 stations (Colab QUICK mode)")
    ap.add_argument("--trials", type=int, default=None, help="Optuna trials per study")
    ap.add_argument("--horizons", type=int, nargs="*", default=None)
    ap.add_argument("--ks", type=int, nargs="*", default=None)
    args = ap.parse_args()
    res = run_tuning(load_config(), args.quick, args.trials, args.horizons, args.ks)
    for h, rows in res["horizons"].items():
        print(f"h={h} (n_val={rows['n_val_eval']}):")
        for name, m in rows["models"].items():
            print(f"  {name:20s} RMSE={m['rmse']:7.2f}  vs B0={m['improvement_vs_b0_pct']:+.1f}%")
    print({"sanity_alarms": res["sanity_alarms"], "runtime_s": res["runtime_s"]})


if __name__ == "__main__":
    main()
