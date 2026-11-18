"""YAML config loading with a stable hash (used in manifests and repro.json)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from airq.env import repo_root


def default_config_path() -> Path:
    return repo_root() / "configs" / "default.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    with (path or default_config_path()).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def config_hash(cfg: dict[str, Any]) -> str:
    blob = json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]
