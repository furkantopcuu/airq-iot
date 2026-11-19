"""Final RQ1 test evaluation, SHAP and LOSO (python -m scripts.run_final [--quick] [--only ...]).

The test split is evaluated ONCE: a guard file blocks re-runs. Run order: test, shap, loso.
"""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.pipelines.rq1_final import evaluate_test, loso, shap_groups


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2 stations (Colab QUICK mode)")
    ap.add_argument("--only", choices=["test", "shap", "loso"], default=None)
    ap.add_argument("--force", action="store_true", help="rebuild outputs (never to chase numbers)")
    args = ap.parse_args()
    cfg = load_config()
    if args.only in (None, "test"):
        print(json.dumps(evaluate_test(cfg, args.quick, args.force), indent=2)[:1500])
    if args.only in (None, "shap"):
        print(shap_groups(cfg, args.quick).to_string(index=False))
    if args.only in (None, "loso"):
        print(loso(cfg, args.quick, args.force).to_string(index=False))


if __name__ == "__main__":
    main()
