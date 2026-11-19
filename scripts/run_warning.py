"""RQ2 early warning: delta on validation, test once (python -m scripts.run_warning)."""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.pipelines.rq2 import run_rq2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild outputs (never to chase numbers)")
    args = ap.parse_args()
    print(json.dumps(run_rq2(load_config(), args.quick, args.force), indent=2))


if __name__ == "__main__":
    main()
