"""RQ3b: faulty sensor inputs, edge filter on/off (python -m scripts.run_robustness)."""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.pipelines.rq3b import run_rq3b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seeds", type=int, nargs="*", default=None)
    ap.add_argument("--force", action="store_true", help="rebuild outputs (never to chase numbers)")
    args = ap.parse_args()
    print(json.dumps(run_rq3b(load_config(), args.quick, args.seeds, args.force), indent=2))


if __name__ == "__main__":
    main()
