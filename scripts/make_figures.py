"""Make figures from reports/ and processed data (python -m scripts.make_figures)."""

from __future__ import annotations

from airq.config import load_config
from airq.pipelines.figures import make_all


def main() -> None:
    made, skipped = make_all(load_config())
    for p in made:
        print(p)
    for stage, why in skipped.items():
        print(f"skipped {stage}: {why}")


if __name__ == "__main__":
    main()
