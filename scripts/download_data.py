"""Download the Beijing dataset and write its SHA-256 (python -m scripts.download_data)."""

from __future__ import annotations

import argparse
import json

from airq.config import load_config
from airq.data.download import download_beijing
from airq.env import resolve_paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    paths = resolve_paths(cfg["paths"])
    info = download_beijing(cfg["data"]["beijing_url"], paths["raw"] / "beijing", args.force)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
