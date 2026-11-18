"""The single feature builder (offline training == online serving).

Contract (spec 4.2): `build_features(df, cfg) -> (features, meta)`, a pure function.
Every feature at time t uses information from <= t only. Never use PM10 (or anything else)
from t+h. The online predictor calls this same function on its rolling buffer.

Input `df`: cleaned frame (see `airq.data.clean.clean`) with a complete hourly calendar per
station, columns: station, ts, pm25, pm10, so2, no2, co, o3, temp, pres, dewp, rain, wspm,
wd_sin, wd_cos and the `<var>_missing` flags. `pm25_raw` is NOT a feature (it is the target source).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

COPOLL = ["pm10", "no2", "co", "o3", "so2"]
METEO = ["temp", "pres", "dewp", "rain", "wspm", "wd_sin", "wd_cos"]
MISSING_VARS = ["pm25", "pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]
ID_COLS = ["station", "ts"]


@dataclass(frozen=True)
class FeatureConfig:
    horizons: tuple[int, ...] = (1, 6, 24)
    pm25_lags: tuple[int, ...] = (0, 1, 2, 3, 6, 12, 24, 48, 72, 168)
    copoll_lags: tuple[int, ...] = (0, 1, 3, 24)
    rolling_windows: tuple[int, ...] = (3, 6, 24, 72)
    meteo_lags: tuple[int, ...] = (0, 1, 3)
    neighbor_k: int = 0  # 0 = single station, >0 = network features
    neighbors: dict[str, list[str]] | None = None  # station -> neighbor stations (fit on train)
    neighbor_lags: tuple[int, ...] = (1, 6, 24)

    @classmethod
    def from_cfg(
        cls, cfg: dict, k: int = 0, neighbors: dict[str, list[str]] | None = None
    ) -> FeatureConfig:
        f = cfg["forecast"]
        return cls(
            horizons=tuple(f["horizons"]),
            pm25_lags=tuple(f["pm25_lags"]),
            copoll_lags=tuple(f["copoll_lags"]),
            rolling_windows=tuple(f["rolling_windows"]),
            neighbor_k=k,
            neighbors=neighbors,
        )


@dataclass
class FeatureMeta:
    feature_names: list[str]
    groups: dict[str, list[str]] = field(default_factory=dict)
    categorical: list[str] = field(default_factory=lambda: ["station"])


def _check_calendar(df: pd.DataFrame) -> None:
    for station, g in df.groupby("station", sort=False):
        step = g["ts"].diff().dropna()
        if len(g) > 1 and not (step == pd.Timedelta(hours=1)).all():
            raise ValueError(f"Station {station}: timestamps must be a complete hourly calendar")


def _neighbor_sets(stations: list[str], cfg: FeatureConfig) -> dict[str, list[str]]:
    if cfg.neighbor_k == 0:
        return {s: [] for s in stations}
    if cfg.neighbors is not None:
        return {s: [n for n in cfg.neighbors.get(s, []) if n != s] for s in stations}
    if cfg.neighbor_k < len(stations) - 1:
        raise ValueError("neighbor_k < n_stations-1 requires explicit `neighbors` (train-fitted)")
    return {s: [n for n in stations if n != s] for s in stations}


def _own_features(g: pd.DataFrame, cfg: FeatureConfig) -> dict[str, dict[str, pd.Series]]:
    """Single-station features, grouped by feature group. Trailing windows only (<= t)."""
    out: dict[str, dict[str, pd.Series]] = {k: {} for k in
        ("pm25_lags", "copoll_lags", "rolling", "meteo", "calendar", "quality")}  # fmt: skip
    pm = g["pm25"]
    for lag in cfg.pm25_lags:
        out["pm25_lags"][f"pm25_lag{lag}"] = pm.shift(lag)
    for var in COPOLL:
        for lag in cfg.copoll_lags:
            out["copoll_lags"][f"{var}_lag{lag}"] = g[var].shift(lag)
    for w in cfg.rolling_windows:
        mp = max(2, -(-w // 2))  # ceil(w/2); the window ends at t and includes t
        r = pm.rolling(w, min_periods=mp)
        out["rolling"][f"pm25_roll{w}_mean"] = r.mean()
        out["rolling"][f"pm25_roll{w}_std"] = r.std()
        out["rolling"][f"pm25_roll{w}_min"] = r.min()
        out["rolling"][f"pm25_roll{w}_max"] = r.max()
    out["rolling"]["pm25_delta1"] = pm - pm.shift(1)
    out["rolling"]["pm25_delta24"] = pm - pm.shift(24)
    for var in METEO:
        for lag in cfg.meteo_lags:
            out["meteo"][f"{var}_lag{lag}"] = g[var].shift(lag)
    out["meteo"]["dewp_minus_temp"] = g["dewp"] - g["temp"]
    out["meteo"]["rain_sum24"] = g["rain"].rolling(24, min_periods=12).sum()
    out["meteo"]["pres_delta3"] = g["pres"] - g["pres"].shift(3)
    ts = g["ts"]
    for name, val, period in (
        ("hour", ts.dt.hour, 24), ("dow", ts.dt.day_of_week, 7), ("month", ts.dt.month - 1, 12),
    ):  # fmt: skip
        ang = 2 * np.pi * val / period
        out["calendar"][f"{name}_sin"] = pd.Series(np.sin(ang), index=g.index)
        out["calendar"][f"{name}_cos"] = pd.Series(np.cos(ang), index=g.index)
    out["calendar"]["is_weekend"] = (ts.dt.day_of_week >= 5).astype(float)
    for var in MISSING_VARS:
        out["quality"][f"{var}_missing"] = g[f"{var}_missing"].astype(float)
    return out


def _neighbor_features(
    wide: pd.DataFrame, station: str, nbrs: list[str], own_pm: pd.Series, cfg: FeatureConfig
) -> dict[str, pd.Series]:
    """Network features from neighbors' PM2.5 at <= t. Missing neighbors are skipped."""
    if not nbrs:
        return {}
    nb = wide[nbrs]
    mean = nb.mean(axis=1)
    med = nb.median(axis=1)
    out = {
        "nb_mean": mean,
        "nb_median": med,
        "nb_min": nb.min(axis=1),
        "nb_max": nb.max(axis=1),
        "nb_std": nb.std(axis=1),
        "nb_diff_median": own_pm.reindex(wide.index) - med,
        "nb_slope3": (mean - mean.shift(3)) / 3.0,
        "n_neighbors_available": nb.notna().sum(axis=1).astype(float),
    }
    for lag in cfg.neighbor_lags:
        out[f"nb_mean_lag{lag}"] = mean.shift(lag)
    return out


def build_features(df: pd.DataFrame, cfg: FeatureConfig) -> tuple[pd.DataFrame, FeatureMeta]:
    """Build features for every row of `df`. Returns (station, ts, features...) and metadata."""
    df = df.sort_values(["station", "ts"]).reset_index(drop=True)
    _check_calendar(df)
    stations = sorted(df["station"].unique())
    nbr_sets = _neighbor_sets(stations, cfg)
    wide = df.pivot(index="ts", columns="station", values="pm25")

    frames = []
    groups: dict[str, list[str]] = {}
    for station, g in df.groupby("station", sort=True):
        g = g.reset_index(drop=True)
        own = _own_features(g, cfg)
        feats: dict[str, pd.Series] = {}
        for gname, cols in own.items():
            for name, s in cols.items():
                feats[name] = s
                groups.setdefault(gname, []).append(name)
        nbr = _neighbor_features(wide, station, nbr_sets[station], g.set_index("ts")["pm25"], cfg)
        for name, s in nbr.items():
            feats[name] = pd.Series(s.reindex(g["ts"]).to_numpy(), index=g.index)
            groups.setdefault("neighbors", []).append(name)
        f = pd.DataFrame(feats).astype("float32")
        f.insert(0, "ts", g["ts"])
        f.insert(0, "station", g["station"])
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out["station"] = pd.Categorical(out["station"], categories=stations)
    groups = {k: list(dict.fromkeys(v)) for k, v in groups.items()}
    groups["station"] = ["station"]
    names = [c for c in out.columns if c not in ID_COLS] + ["station"]
    names = list(dict.fromkeys(names))
    return out, FeatureMeta(feature_names=names, groups=groups)


def make_target(df: pd.DataFrame, h: int) -> pd.Series:
    """y = observed PM2.5 at t+h (never filled). NaN rows must be dropped by the caller."""
    df = df.sort_values(["station", "ts"]).reset_index(drop=True)
    return df.groupby("station", sort=True)["pm25_raw"].shift(-h)
