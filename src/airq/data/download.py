"""Download and verify the Beijing Multi-Site Air-Quality dataset (UCI #501)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import requests

ZIP_NAME = "beijing_multi_site.zip"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str, dest: Path, retries: int = 5) -> None:
    """Download to a .part file and rename only when complete and a valid zip."""
    part = dest.with_suffix(dest.suffix + ".part")
    last: Exception | None = None
    for _ in range(retries):
        try:
            with requests.get(url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with part.open("wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
            if not zipfile.is_zipfile(part):
                raise OSError("downloaded file is not a valid zip")
            part.replace(dest)
            return
        except (requests.RequestException, OSError) as exc:
            last = exc
    part.unlink(missing_ok=True)
    raise RuntimeError(f"Download failed after {retries} attempts: {last}")


def download_beijing(url: str, raw_dir: Path, force: bool = False) -> dict:
    """Download + extract the dataset into `raw_dir`; returns {zip, sha256, csv_dir}."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / ZIP_NAME
    if force or not zip_path.exists():
        _fetch(url, zip_path)
    digest = sha256_file(zip_path)
    extract_dir = raw_dir / "extracted"
    if force or not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    # the UCI zip may nest another zip; unpack it once
    for inner in extract_dir.rglob("*.zip"):
        target = inner.with_suffix("")
        if not target.exists():
            with zipfile.ZipFile(inner) as zf:
                zf.extractall(target)
    csvs = sorted(extract_dir.rglob("PRSA_Data_*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No PRSA_Data_*.csv found under {extract_dir}")
    info = {"zip": zip_path.name, "sha256": digest, "csv_dir": str(csvs[0].parent), "n_csv": len(csvs)}
    (raw_dir / "download.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info
