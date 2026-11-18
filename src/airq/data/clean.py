"""Past-only cleaning: full hourly calendar, wind encoding, causal forward fill.

Forbidden here (leakage): bfill, bidirectional interpolation, imputers/scalers fit on all data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from airq.data.load import VALUE_COLS

WIND_DEG = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}  # fmt: skip


def wind_to_sincos(wd: pd.Series) -> tuple[pd.Series, pd.Series]:
    """16-point wind direction -> (sin, cos); both NaN when direction is missing."""
    rad = np.deg2rad(wd.map(WIND_DEG).astype(float))
    return np.sin(rad), np.cos(rad)


def clean(df: pd.DataFrame, start: str, end: str, ffill_limit: int = 3) -> pd.DataFrame:
    """Reindex every station to a full hourly calendar and forward-fill (limit) per station.

    Adds `<var>_missing` (state BEFORE filling) and `pm25_raw` (observed PM2.5, never filled).
    """
    full = pd.date_range(start, end, freq="h")
    parts = []
    for station, g in df.groupby("station", sort=True):
        g = g.drop_duplicates("ts").set_index("ts").reindex(full)
        g.index.name = "ts"
        g["station"] = station
        g["wd_sin"], g["wd_cos"] = wind_to_sincos(g["wd"])
        for col in VALUE_COLS:
            g[f"{col}_missing"] = g[col].isna()
        g["pm25_raw"] = g["pm25"]
        fill_cols = [*VALUE_COLS, "wd_sin", "wd_cos"]
        g[fill_cols] = g[fill_cols].ffill(limit=ffill_limit)
        parts.append(g.reset_index().drop(columns=["wd"]))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["station", "ts"]).reset_index(drop=True)
