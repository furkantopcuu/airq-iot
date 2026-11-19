"""Deterministic synthetic stand-in for the Beijing CSVs (used for CI notebooks and tests).

Same file layout and columns as the UCI download, but synthetic values and only a few stations.
It exists so notebooks can run in CI without internet access or the real dataset.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FIXTURE_STATIONS = ["Aotizhongxin", "Changping", "Dongsi", "Huairou"]
WIND = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]  # fmt: skip


def make_fixture_raw(
    raw_dir: Path, start: str = "2013-03-01", end: str = "2017-02-28 23:00", seed: int = 0
) -> Path:
    """Write PRSA_Data_*.csv files under raw_dir/extracted/fixture and return that folder."""
    out = Path(raw_dir) / "beijing" / "extracted" / "fixture"
    out.mkdir(parents=True, exist_ok=True)
    ts = pd.date_range(start, end, freq="h")
    n = len(ts)
    rng = np.random.default_rng(seed)
    # shared regional pollution: slow AR(1) + winter seasonality, with occasional haze bursts
    regional = np.zeros(n)
    for i in range(1, n):
        regional[i] = 0.97 * regional[i - 1] + rng.normal(0, 4)
    season = 35 * np.cos(2 * np.pi * (ts.day_of_year.to_numpy() - 15) / 365.25)
    base = np.clip(70 + season + regional, 3, 600)
    for k, st in enumerate(FIXTURE_STATIONS):
        pm25 = np.clip(base * rng.uniform(0.9, 1.1) + rng.normal(0, 8, n) + k * 2, 2, 900).round()
        pm10 = (pm25 * rng.uniform(1.1, 1.6, n)).round()
        df = pd.DataFrame(
            {
                "No": np.arange(1, n + 1),
                "year": ts.year,
                "month": ts.month,
                "day": ts.day,
                "hour": ts.hour,
                "PM2.5": pm25,
                "PM10": pm10,
                "SO2": rng.gamma(2.0, 5.0, n).round(),
                "NO2": rng.gamma(4.0, 12.0, n).round(),
                "CO": (rng.gamma(3.0, 350.0, n) + 100).round(),
                "O3": rng.gamma(2.0, 25.0, n).round(),
                "TEMP": 12
                + 14 * np.cos(2 * np.pi * (ts.day_of_year.to_numpy() - 200) / 365.25)
                + rng.normal(0, 2, n),
                "PRES": 1012 + rng.normal(0, 6, n),
                "DEWP": 2
                + 10 * np.cos(2 * np.pi * (ts.day_of_year.to_numpy() - 200) / 365.25)
                + rng.normal(0, 3, n),
                "RAIN": np.where(rng.random(n) < 0.03, rng.gamma(1.0, 1.0, n), 0.0),
                "wd": rng.choice(WIND, n),
                "WSPM": rng.gamma(2.0, 1.0, n),
                "station": st,
            }
        )
        miss = rng.random(n) < 0.02  # ~2% missing, like the real data
        df.loc[miss, ["PM2.5", "PM10"]] = np.nan
        df.to_csv(out / f"PRSA_Data_{st}_fixture.csv", index=False)
    return out
