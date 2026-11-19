"""Make figures from reports/ and processed data (python -m scripts.make_figures)."""

from __future__ import annotations

from airq.config import load_config
from airq.pipelines.figures import eda, rq1, rq2, rq3a, rq3b


def main() -> None:
    cfg = load_config()
    for p in eda(cfg):
        print(p)
    try:
        for p in [*rq1(cfg), *rq2(cfg), *rq3b(cfg), *rq3a(cfg)]:
            print(p)
    except FileNotFoundError:
        print("RQ tables not found yet; run run_final, run_warning and run_robustness first")


if __name__ == "__main__":
    main()
