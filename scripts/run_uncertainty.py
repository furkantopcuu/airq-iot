"""RQ4: quantile forecasts, calibration, q90 warning (python -m scripts.run_uncertainty).

The test split is evaluated ONCE: a guard file blocks re-runs (see airq.pipelines.rq4).
"""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.pipelines.rq4 import run_uncertainty


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="2 stations (pipeline smoke test)")
    ap.add_argument("--force", action="store_true", help="rebuild outputs (never to chase numbers)")
    args = ap.parse_args()
    print(json.dumps(run_uncertainty(load_config(), args.quick, args.force), indent=2)[:1500])


if __name__ == "__main__":
    main()
