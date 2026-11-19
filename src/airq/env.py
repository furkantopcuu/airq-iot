"""Environment detection (local vs Colab) and path resolution."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/airq-iot")
COLAB_ROOT = Path("/content/airq-iot")


def is_colab() -> bool:
    return "google.colab" in sys.modules


def repo_root() -> Path:
    """Repository root when running from a source checkout."""
    return Path(__file__).resolve().parents[2]


def mount_drive_if_wanted(use_drive: bool) -> bool:
    """Mount Google Drive only when asked to and running on Colab."""
    if not (use_drive and is_colab()):
        return False
    from google.colab import drive  # type: ignore[import-not-found]

    drive.mount("/content/drive")
    return True


def is_fixture() -> bool:
    """AIRQ_FIXTURE=1: use small synthetic data in a temp dir; never touch the network or repo."""
    return os.environ.get("AIRQ_FIXTURE", "") not in ("", "0", "false")


def resolve_home() -> Path:
    """AIRQ_HOME -> fixture temp dir -> Drive (Colab) -> /content/airq-iot -> repo root (local)."""
    env_home = os.environ.get("AIRQ_HOME")
    if env_home:
        return Path(env_home)
    if is_fixture():
        return Path(tempfile.gettempdir()) / "airq-fixture"
    if is_colab():
        return DRIVE_ROOT if DRIVE_ROOT.parent.exists() else COLAB_ROOT
    return repo_root()


def resolve_paths(cfg_paths: dict[str, str]) -> dict[str, Path]:
    """Turn the relative `paths` section of the config into absolute paths."""
    home = resolve_home()
    return {name: home / rel for name, rel in cfg_paths.items()}
