"""Fit edge quality thresholds on train (python -m scripts.fit_edge)."""

from __future__ import annotations

import json

from airq.config import load_config
from airq.pipelines.edge import run


def main() -> None:
    print(json.dumps(run(load_config()), indent=2))


if __name__ == "__main__":
    main()
