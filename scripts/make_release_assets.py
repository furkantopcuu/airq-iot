"""Build the release assets from a local run (python -m scripts.make_release_assets).

Writes release/airq_models.zip, release/demo_recorded.db (if data/demo_recorded.db or --demo is
given), release/SHA256SUMS.txt and fills the checksums into configs/release.yaml. The `release/`
folder is git-ignored; upload its files to the GitHub Release by hand.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from airq.config import load_config
from airq.env import repo_root, resolve_paths
from airq.pipelines.release import DEMO_DB, MODELS_ZIP, build_models_zip, sha256_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--demo", type=Path, help="recorded SQLite to ship (default data/demo_recorded.db)"
    )
    args = ap.parse_args()
    paths = resolve_paths(load_config()["paths"])
    out = repo_root() / "release"
    out.mkdir(exist_ok=True)
    names = build_models_zip(paths["models"], out / MODELS_ZIP)
    print(f"{MODELS_ZIP}: {len(names)} files")
    demo = args.demo or paths["db"].parent / DEMO_DB
    sums = {MODELS_ZIP: sha256_file(out / MODELS_ZIP)}
    if demo.exists():
        shutil.copy2(demo, out / DEMO_DB)
        sums[DEMO_DB] = sha256_file(out / DEMO_DB)
        print(f"{DEMO_DB}: {(out / DEMO_DB).stat().st_size / 1e6:.2f} MB")
    (out / "SHA256SUMS.txt").write_text(
        "".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="utf-8"
    )
    cfg_path = repo_root() / "configs" / "release.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    for name, h in sums.items():
        text = re.sub(
            rf"({re.escape(name)}:.*?sha256: )\S+", rf"\g<1>{h}", text, count=1, flags=re.S
        )
    cfg_path.write_text(text, encoding="utf-8")
    print("checksums written to configs/release.yaml")


if __name__ == "__main__":
    main()
