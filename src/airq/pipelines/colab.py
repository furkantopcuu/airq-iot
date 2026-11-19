"""Helpers for notebooks: environment summary and artifact export/import (spec 14.4)."""

from __future__ import annotations

import json
import os
import platform
import sys
import zipfile
from datetime import date
from importlib import metadata
from pathlib import Path

from airq.env import is_colab, is_fixture, resolve_paths

ARTIFACT_DIRS = ("reports", "models")


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def env_summary(cfg: dict) -> dict:
    """Python/library versions, CPU/RAM, Colab flag and resolved paths (for the notebook header)."""
    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / 1e9, 1)
    except ImportError:
        ram_gb = None
    paths = resolve_paths(cfg["paths"])
    return {
        "python": platform.python_version(),
        "lightgbm": _version("lightgbm"),
        "pandas": _version("pandas"),
        "cpu_count": os.cpu_count(),
        "ram_gb": ram_gb,
        "is_colab": is_colab(),
        "fixture_mode": is_fixture(),
        "reports_dir": paths["reports"].name,
        "data_dir": paths["raw"].parent.name,
    }


def export_artifacts(cfg: dict, out_dir: Path | None = None) -> Path:
    """Zip reports/ and models/ as airq_artifacts_<date>.zip (small files only)."""
    paths = resolve_paths(cfg["paths"])
    out_dir = out_dir or paths["reports"].parent
    out = out_dir / f"airq_artifacts_{date.today().isoformat()}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ARTIFACT_DIRS:
            root = paths[name]
            if not root.exists():
                continue
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.stat().st_size < 50_000_000:
                    zf.write(f, f"{name}/{f.relative_to(root).as_posix()}")
    return out


def import_artifacts(zip_path: Path, cfg: dict) -> list[str]:
    """Unpack an artifact zip into reports/ and models/, then check the model manifest."""
    paths = resolve_paths(cfg["paths"])
    written = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            top, _, rest = member.partition("/")
            if top not in ARTIFACT_DIRS or not rest or ".." in Path(member).parts:
                continue  # ignore anything outside reports/ and models/ (zip-slip safe)
            target = paths[top] / rest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
            written.append(member)
    check_manifest(paths["models"])
    return written


def check_manifest(models_dir: Path) -> None:
    """Every model file listed in manifest.json must exist and the LightGBM major must match."""
    manifest_path = models_dir / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [
        e["file"]
        for e in manifest.get("models", {}).values()
        if not (models_dir / e["file"]).exists()
    ]
    if missing:
        raise FileNotFoundError(f"manifest lists missing model files: {missing[:5]}")
    saved = manifest.get("lightgbm_version")
    now = _version("lightgbm")
    if saved and now and saved.split(".")[0] != now.split(".")[0]:
        raise RuntimeError(f"LightGBM major version mismatch: trained {saved}, now {now}")


if __name__ == "__main__":  # pragma: no cover
    print(sys.version)
