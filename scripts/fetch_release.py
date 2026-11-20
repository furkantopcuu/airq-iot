"""Download the trained models / the demo recording from the GitHub Release (checksum verified).

python -m scripts.fetch_release                 models + demo recording
python -m scripts.fetch_release --only models   only the trained models (needed by the live demo)
"""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.env import resolve_paths
from airq.models.manifest import ManifestError
from airq.pipelines.colab import check_manifest
from airq.pipelines.release import fetch


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--only", choices=["models", "demo"], help="fetch one asset kind only")
    args = ap.parse_args()
    placed = fetch(only=args.only)
    for p in placed:
        print("wrote", p.name)
    if args.only != "demo":
        try:
            check_manifest(resolve_paths(load_config()["paths"])["models"])
            print("model manifest check passed")
        except (FileNotFoundError, ManifestError, RuntimeError) as exc:
            raise SystemExit(f"manifest check failed: {exc}") from exc


if __name__ == "__main__":
    main()
