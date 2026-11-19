"""Unpack an airq_artifacts_<date>.zip (e.g. trained on Colab) into reports/ and models/.

python -m scripts.import_artifacts path\to\airq_artifacts_2026-11-20.zip
"""

from __future__ import annotations

import argparse
from pathlib import Path

from airq.config import load_config
from airq.pipelines.colab import import_artifacts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", type=Path)
    args = ap.parse_args()
    written = import_artifacts(args.zip, load_config())
    print(f"Imported {len(written)} files; manifest check passed.")


if __name__ == "__main__":
    main()
