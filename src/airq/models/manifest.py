"""Model manifest: guards against feature/version mismatch when a model is loaded (spec 14.3)."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb

from airq.env import is_colab, repo_root


class ManifestError(RuntimeError):
    pass


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_short_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _major(version: str) -> str:
    return version.split(".")[0]


def read_manifest(models_dir: Path) -> dict:
    path = models_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"models": {}}


def record_model(
    models_dir: Path, key: str, model_file: str, feature_names: list[str], config_hash: str
) -> dict:
    """Add/replace one model entry and rewrite manifest.json."""
    manifest = read_manifest(models_dir)
    manifest.update(
        {
            "lightgbm_version": lgb.__version__,
            "python": platform.python_version(),
            "environment": "colab" if is_colab() else "local",
            "git_commit": git_short_hash(),
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "neighbors_sha256": file_sha256(models_dir / "neighbors.json"),
            "warning_thresholds_sha256": file_sha256(models_dir / "warning_thresholds.json"),
        }
    )
    manifest.setdefault("models", {})[key] = {
        "file": model_file,
        "features": feature_names,
        "config_hash": config_hash,
        "hparams_sha256": file_sha256(models_dir / f"hparams_{key}.json"),
    }
    (models_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_model_checked(models_dir: Path, key: str, feature_names: list[str]) -> lgb.Booster:
    """Load a LightGBM model only if its feature list/order and LightGBM major version match."""
    manifest = read_manifest(models_dir)
    entry = manifest.get("models", {}).get(key)
    if entry is None:
        raise ManifestError(f"Model '{key}' is not in manifest.json")
    if entry["features"] != list(feature_names):
        missing = set(entry["features"]) ^ set(feature_names)
        raise ManifestError(
            f"Feature list/order mismatch for '{key}' (differing names: {sorted(missing)[:8]})"
        )
    saved = manifest.get("lightgbm_version", "")
    if saved and _major(saved) != _major(lgb.__version__):
        raise ManifestError(
            f"LightGBM major version mismatch: trained {saved}, now {lgb.__version__}"
        )
    return lgb.Booster(model_file=str(models_dir / entry["file"]))
