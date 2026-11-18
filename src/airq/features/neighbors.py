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
