"""Build cleaned dataset, summary tables, episodes, repro.json (python -m scripts.make_dataset)."""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.pipelines.data import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2 stations only (Colab QUICK mode)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    print(run(load_config(), quick=args.quick, force=args.force))


if __name__ == "__main__":
    main()
