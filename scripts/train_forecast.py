"""RQ1 v0: baselines + LightGBM on validation (python -m scripts.train_forecast)."""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.pipelines.rq1 import run_v0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2 stations (Colab QUICK mode)")
    args = ap.parse_args()
    res = run_v0(load_config(), quick=args.quick)
    for h, rows in res["horizons"].items():
        print(f"h={h} (n_val={rows['n_val_eval']}):")
        for name, m in rows["models"].items():
            gain = m["improvement_vs_b0_pct"]
            print(f"  {name:20s} RMSE={m['rmse']:7.2f}  R2={m['r2']:.3f}  vs B0={gain:+.1f}%")
    print(json.dumps({"sanity_alarms": res["sanity_alarms"], "runtime_s": res["runtime_s"]}))


if __name__ == "__main__":
    main()
