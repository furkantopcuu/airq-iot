"""Read the raw Beijing CSVs into one tidy frame."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RENAME = {
    "PM2.5": "pm25",
    "PM10": "pm10",
    "SO2": "so2",
    "NO2": "no2",
    "CO": "co",
    "O3": "o3",
    "TEMP": "temp",
    "PRES": "pres",
    "DEWP": "dewp",
    "RAIN": "rain",
    "WSPM": "wspm",
}
VALUE_COLS = ["pm25", "pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]


def load_raw(csv_dir: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(Path(csv_dir).glob("PRSA_Data_*.csv"))]
    if not frames:
        raise FileNotFoundError(f"No PRSA_Data_*.csv in {csv_dir}")
    df = pd.concat(frames, ignore_index=True).rename(columns=RENAME)
    # ts is timezone-naive Asia/Shanghai local time; no conversion (spec 2.3)
    df["ts"] = pd.to_datetime(df[["year", "month", "day", "hour"]])
    cols = ["station", "ts", *VALUE_COLS, "wd"]
    return df[cols].sort_values(["station", "ts"]).reset_index(drop=True)
