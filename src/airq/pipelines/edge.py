"""Fit the edge quality thresholds on TRAIN and report how often each rule fires on clean data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from airq.config import load_config
from airq.edge.quality import ALL_FLAGS, QualityParams, fit_params, flag_frame
from airq.env import resolve_paths


def params_path(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return resolve_paths(cfg["paths"])["reports"] / "metrics" / "edge_params.json"


def load_params(cfg: dict | None = None) -> QualityParams:
    path = params_path(cfg)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `python -m scripts.fit_edge` first")
    return QualityParams.from_dict(json.loads(path.read_text(encoding="utf-8"))["params"])


def run(cfg: dict) -> dict:
    paths = resolve_paths(cfg["paths"])
    df = pd.read_parquet(paths["processed"] / "clean.parquet")
    df = df.sort_values(["station", "ts"]).reset_index(drop=True)
    train = df[df["split"] == "train"]
    params = fit_params(train, cfg)
    rates = {}
    for split in ("train", "val", "test"):
        part = df[df["split"] == split].reset_index(drop=True)
        flags = flag_frame(part, params)
        rates[split] = {f: round(100 * float(flags[f].mean()), 4) for f in ALL_FLAGS}
    out = {
        "fit_on": "train",
        "params": params.to_dict(),
        "clean_data_flag_rate_pct": rates,
        "note": "rates are on CLEAN recorded data: any non-'missing' flag here is a false alarm",
    }
    target = params_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
