"""Regional haze episodes and per-station exceedance events (spec 2.5)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of consecutive True runs."""
    padded = np.concatenate([[False], mask, [False]]).astype(int)
    diff = np.diff(padded)
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1) - 1
    return list(zip(starts, ends, strict=True))


def regional_haze(
    pm25: pd.DataFrame, min_stations: int = 8, threshold: float = 150, min_hours: int = 6
) -> pd.DataFrame:
    """`pm25` is wide (index=ts hourly, columns=stations). NaN never counts as exceeding."""
    n_over = (pm25 > threshold).sum(axis=1).to_numpy()
    idx = pm25.index
    rows = []
    for s, e in _runs(n_over >= min_stations):
        if e - s + 1 >= min_hours:
            block = pm25.iloc[s : e + 1]
            rows.append(
                {
                    "type": "regional_haze",
                    "station": "ALL",
                    "threshold": threshold,
                    "start": idx[s],
                    "end": idx[e],
                    "hours": e - s + 1,
                    "peak": float(block.max().max()),
                }
            )
    return pd.DataFrame(rows, columns=_COLS)


_COLS = ["type", "station", "threshold", "start", "end", "hours", "peak"]


def exceedance_events(
    series: pd.Series, station: str, theta: float, min_hours: int = 3, merge_gap_h: int = 6
) -> pd.DataFrame:
    """Blocks with PM2.5 > theta for >= min_hours; blocks separated by < merge_gap_h non-exceeding
    hours are merged. Onset = first hour of the merged block. NaN counts as not exceeding."""
    vals = series.to_numpy(dtype=float)
    idx = series.index
    blocks = [(s, e) for s, e in _runs(np.nan_to_num(vals, nan=-1.0) > theta) if e - s + 1 >= min_hours]
    merged: list[list[int]] = []
    for s, e in blocks:
        if merged and s - merged[-1][1] - 1 < merge_gap_h:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    rows = [
        {
            "type": "exceedance",
            "station": station,
            "threshold": theta,
            "start": idx[s],
            "end": idx[e],
            "hours": e - s + 1,
            "peak": float(np.nanmax(vals[s : e + 1])),
        }
        for s, e in merged
    ]
    return pd.DataFrame(rows, columns=_COLS)


def label_all(pm25_wide: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """All haze and exceedance episodes, tagged with the split of their onset."""
    from airq.data.splits import assign_split

    ep = cfg["episodes"]
    parts = [
        regional_haze(pm25_wide, ep["haze"]["min_stations"], ep["haze"]["threshold"], ep["haze"]["min_hours"])
    ]
    for station in pm25_wide.columns:
        for theta in ep["exceedance"]["thresholds"]:
            parts.append(
                exceedance_events(
                    pm25_wide[station], station, theta,
                    ep["exceedance"]["min_hours"], ep["exceedance"]["merge_gap_h"],
                )
            )  # fmt: skip
    out = pd.concat(parts, ignore_index=True)
    out["split"] = assign_split(out["start"], cfg).to_numpy()
    return out.sort_values(["type", "start", "station"]).reset_index(drop=True)
