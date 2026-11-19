"""Make figures from reports/ and processed data (python -m scripts.make_figures)."""

from __future__ import annotations

from airq.config import load_config
from airq.pipelines.figures import eda, rq1, rq2


def main() -> None:
    cfg = load_config()
    for p in eda(cfg):
        print(p)
    try:
        for p in [*rq1(cfg), *rq2(cfg)]:
            print(p)
    except FileNotFoundError:
        print("RQ1/RQ2 tables not found yet; run scripts.run_final and scripts.run_warning first")


if __name__ == "__main__":
    main()
