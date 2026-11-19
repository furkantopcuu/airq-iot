"""Make figures from reports/ and processed data (python -m scripts.make_figures)."""

from __future__ import annotations

from airq.config import load_config
from airq.pipelines.figures import eda, rq1


def main() -> None:
    cfg = load_config()
    for p in eda(cfg):
        print(p)
    try:
        for p in rq1(cfg):
            print(p)
    except FileNotFoundError:
        print("RQ1 tables not found yet; run scripts.run_final first")


if __name__ == "__main__":
    main()
