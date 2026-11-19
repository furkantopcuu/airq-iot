"""Make figures from reports/ and processed data (python -m scripts.make_figures)."""

from __future__ import annotations

from airq.config import load_config
from airq.pipelines.figures import eda


def main() -> None:
    for p in eda(load_config()):
        print(p)


if __name__ == "__main__":
    main()
