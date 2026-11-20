"""Release assets: trained models and a recorded demo database, fetched with a checksum.

The repository does not contain trained models (they are GitHub Release assets, spec 13.2). A
visitor runs `python -m scripts.fetch_release` instead of training for an hour: it downloads the
assets named in `configs/release.yaml`, verifies their SHA-256 and unpacks the models next to the
code. `scripts/make_release_assets.py` builds the same assets from a local run.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from pathlib import Path

import yaml

from airq.env import repo_root, resolve_home

MODELS_ZIP = "airq_models.zip"
DEMO_DB = "demo_recorded.db"
MODEL_SUFFIXES = (".txt", ".json")  # LightGBM text models, manifest, hyper-parameters, thresholds


class ChecksumError(RuntimeError):
    pass


def load_release_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or repo_root() / "configs" / "release.yaml").read_text("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_models_zip(models_dir: Path, out: Path) -> list[str]:
    """Zip the model files (not the Optuna database) with paths relative to the home."""
    names = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(models_dir.iterdir()):
            if p.is_file() and p.suffix in MODEL_SUFFIXES:
                z.write(p, f"models/{p.name}")
                names.append(p.name)
    return names


def safe_unzip(archive: Path, target: Path) -> list[str]:
    """Extract under `target`, refusing absolute paths and `..` (zip-slip)."""
    target = target.resolve()
    written = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            dest = (target / info.filename).resolve()
            if not str(dest).startswith(str(target)):
                raise ValueError(f"unsafe path in archive: {info.filename!r}")
            if info.is_dir():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            written.append(info.filename)
    return written


def http_download(url: str, dest: Path) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def fetch(
    cfg: dict | None = None,
    only: str | None = None,
    home: Path | None = None,
    downloader: Callable[[str, Path], None] = http_download,
) -> list[Path]:
    """Download, verify and place the release assets; returns the files that were written."""
    cfg = cfg or load_release_config()
    home = Path(home) if home else resolve_home()
    placed: list[Path] = []
    for name, spec in cfg["assets"].items():
        if only and spec["kind"] != only:
            continue
        expected = spec.get("sha256")
        if not expected or str(expected).startswith("TODO"):
            raise ChecksumError(
                f"{name}: no checksum in configs/release.yaml (release not built yet)"
            )
        tmp = home / ".downloads" / name
        downloader(f"{cfg['base_url']}/{cfg['tag']}/{name}", tmp)
        got = sha256_file(tmp)
        if got != expected:
            tmp.unlink(missing_ok=True)
            raise ChecksumError(f"{name}: SHA-256 mismatch (expected {expected}, got {got})")
        if spec["kind"] == "models":
            placed += [home / n for n in safe_unzip(tmp, home)]
        else:
            dest = home / spec["dest"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tmp.read_bytes())
            placed.append(dest)
    return placed
