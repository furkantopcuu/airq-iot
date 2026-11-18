"""Fixed chronological split (spec 2.4). Same timestamps -> same split for every station."""

from __future__ import annotations

import pandas as pd

SPLITS = ("train", "val", "test")


def split_bounds(cfg: dict) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    return {s: (pd.Timestamp(cfg["split"][s][0]), pd.Timestamp(cfg["split"][s][1])) for s in SPLITS}


def assign_split(ts: pd.Series | pd.DatetimeIndex, cfg: dict) -> pd.Series:
    """Label each timestamp train/val/test; timestamps outside all bounds get <NA>."""
    ts = pd.Series(pd.DatetimeIndex(ts))
    out = pd.Series(pd.NA, index=ts.index, dtype="object")
    for name, (lo, hi) in split_bounds(cfg).items():
        out[(ts >= lo) & (ts <= hi)] = name
    return out


def horizon_mask(ts: pd.Series | pd.DatetimeIndex, split: str, h: int, cfg: dict) -> pd.Series:
    """Rows usable for horizon `h` in `split`: both t and the target time t+h lie inside it.

    Rows whose target falls in a later split are dropped, which also guarantees >= 24 h
    separation between splits. Feature lags may still look back across the boundary.
    """
    lo, hi = split_bounds(cfg)[split]
    ts = pd.Series(pd.DatetimeIndex(ts))
    target = ts + pd.Timedelta(hours=h)
    return (ts >= lo) & (ts <= hi) & (target >= lo) & (target <= hi)
