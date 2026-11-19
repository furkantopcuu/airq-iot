"""Neighbor selection (spec 4.2.6): top-k PM2.5-correlated stations, fit on TRAIN only."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def select_neighbors(
    df: pd.DataFrame, k: int, train_end: str | pd.Timestamp
) -> dict[str, list[str]]:
    """For each station, the k other stations with the highest PM2.5 correlation.

    Uses only rows with ts <= train_end (observed, unfilled PM2.5). No coordinates exist in the
    dataset, so correlation is the proximity proxy.
    """
    train = df[df["ts"] <= pd.Timestamp(train_end)]
    wide = train.pivot(index="ts", columns="station", values="pm25_raw")
    corr = wide.corr()
    out: dict[str, list[str]] = {}
    for station in corr.columns:
        ranked = corr[station].drop(station).sort_values(ascending=False, kind="stable")
        out[station] = list(ranked.index[:k])
    return out


def save_neighbors(neighbors: dict[str, dict[str, list[str]]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(neighbors, indent=2, sort_keys=True), encoding="utf-8")


def ensure_neighbors(df: pd.DataFrame, cfg: dict, path: Path) -> dict[str, dict[str, list[str]]]:
    """Write models/neighbors.json ({"k3": {station: [...]}}) from TRAIN data if it is missing.

    The live predictor loads exactly these neighbor sets, so online and offline agree.
    """
    import json

    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    n = df["station"].nunique()
    out = {
        f"k{k}": select_neighbors(df, k, cfg["split"]["train"][1])
        for k in cfg["forecast"]["neighbor_k"]
        if 0 < k < n - 1
    }
    save_neighbors(out, path)
    return out
