"""Data-quality rules for PM2.5 (spec 8.3), shared by offline experiments and the live edge.

Two implementations of ONE definition, tested for exact parity:
  * `flag_series`  - vectorized, used offline (RQ3b, feature building);
  * `StreamChecker` - incremental, used by the edge gateway on the live stream.

Flags: missing | out_of_range | rate_jump | stuck | pm_inconsistent. (`seq_gap` / `duplicate`
are message-level flags added by the gateway.) A flag other than `missing` marks the PM2.5
value as untrustworthy; with the edge filter ON that value is replaced by null.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

MISSING = "missing"
OUT_OF_RANGE = "out_of_range"
RATE_JUMP = "rate_jump"
STUCK = "stuck"
PM_INCONSISTENT = "pm_inconsistent"
VALUE_FLAGS = (OUT_OF_RANGE, RATE_JUMP, STUCK, PM_INCONSISTENT)  # make the value untrustworthy
ALL_FLAGS = (MISSING, *VALUE_FLAGS)


@dataclass(frozen=True)
class QualityParams:
    lo: float = 0.0
    hi: float = 999.0
    stuck_n: int = 4  # n consecutive equal observed values
    tau_rate: float = 200.0  # |PM2.5(t) - PM2.5(t-1)| above this is a jump (fit on train)
    pm_eps: float = 0.1  # rule: PM2.5 <= PM10 * (1 + eps) + c  (fit on train)
    pm_c: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> QualityParams:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def fit_params(train: pd.DataFrame, cfg: dict) -> QualityParams:
    """Fit thresholds on TRAIN rows only. `train` has station, ts, pm25_raw and pm10 (+ flags)."""
    e = cfg["edge"]
    obs = train.sort_values(["station", "ts"])
    diffs = obs.groupby("station", sort=True)["pm25_raw"].diff().abs().dropna()
    tau = float(diffs.quantile(e["rate_quantile"]))
    pm10 = obs["pm10"].where(~obs["pm10_missing"]) if "pm10_missing" in obs else obs["pm10"]
    pair = pd.DataFrame({"pm25": obs["pm25_raw"], "pm10": pm10}).dropna()
    eps = e["pm_consistency"]["eps"]
    eps = 0.1 if eps is None else float(eps)
    excess = (pair["pm25"] - pair["pm10"] * (1 + eps)).clip(lower=0)
    c = e["pm_consistency"]["c"]
    c = float(excess.quantile(e["rate_quantile"])) if c is None else float(c)
    return QualityParams(
        lo=float(e["range"][0]),
        hi=float(e["range"][1]),
        stuck_n=int(e["stuck_n"]),
        tau_rate=tau,
        pm_eps=eps,
        pm_c=c,
    )


def flag_series(pm25: pd.Series, pm10: pd.Series, p: QualityParams) -> pd.DataFrame:
    """Vectorized flags for ONE station on a complete hourly index (NaN = missing)."""
    x = pm25.astype(float)
    prev = x.shift(1)
    both = x.notna() & prev.notna()
    eq = both & (x == prev)
    n_eq = max(p.stuck_n - 1, 1)
    stuck = eq.astype(int).rolling(n_eq, min_periods=n_eq).sum() == n_eq
    out = pd.DataFrame(index=x.index)
    out[MISSING] = x.isna()
    out[OUT_OF_RANGE] = x.notna() & ((x < p.lo) | (x > p.hi))
    out[RATE_JUMP] = both & ((x - prev).abs() > p.tau_rate)
    out[STUCK] = stuck
    out[PM_INCONSISTENT] = x.notna() & pm10.notna() & (x > pm10 * (1 + p.pm_eps) + p.pm_c)
    return out.fillna(False).astype(bool)


def flag_frame(df: pd.DataFrame, p: QualityParams, pm25_col: str = "pm25_raw") -> pd.DataFrame:
    """Offline flags for every row (same order as `df`); input must be sorted by station, ts."""
    pm10 = df["pm10"].where(~df["pm10_missing"]) if "pm10_missing" in df else df["pm10"]
    parts = []
    for _, idx in df.groupby("station", sort=False).groups.items():
        parts.append(flag_series(df.loc[idx, pm25_col], pm10.loc[idx], p))
    return pd.concat(parts).loc[df.index]


class StreamChecker:
    """Incremental version of the same rules for one station (state = last n values)."""

    def __init__(self, p: QualityParams):
        self.p = p
        self._last: float | None = None
        self._eq_run = 0  # consecutive equalities ending at the previous value

    def update(self, pm25: float | None, pm10: float | None) -> list[str]:
        p = self.p
        flags: list[str] = []
        x = None if pm25 is None or (isinstance(pm25, float) and np.isnan(pm25)) else float(pm25)
        if x is None:
            flags.append(MISSING)
            self._last, self._eq_run = None, 0
            return flags
        if x < p.lo or x > p.hi:
            flags.append(OUT_OF_RANGE)
        prev = self._last
        if prev is not None and abs(x - prev) > p.tau_rate:
            flags.append(RATE_JUMP)
        self._eq_run = self._eq_run + 1 if prev is not None and x == prev else 0
        if self._eq_run >= max(p.stuck_n - 1, 1):
            flags.append(STUCK)
        if pm10 is not None and not np.isnan(pm10) and x > pm10 * (1 + p.pm_eps) + p.pm_c:
            flags.append(PM_INCONSISTENT)
        self._last = x
        return flags


def value_is_untrustworthy(flags: list[str] | set[str]) -> bool:
    return any(f in VALUE_FLAGS for f in flags)


def apply_filter(pm25: pd.Series, flags: pd.DataFrame) -> pd.Series:
    """Offline equivalent of the edge filter: untrustworthy PM2.5 values become NaN."""
    bad = flags[list(VALUE_FLAGS)].any(axis=1)
    return pm25.where(~bad)


# kept for readers: a tiny deque-based reference of the stuck rule (used only in tests/docs)
def _stuck_reference(values: list[float | None], n: int) -> list[bool]:
    window: deque[float | None] = deque(maxlen=n)
    out = []
    for v in values:
        window.append(v)
        out.append(
            len(window) == n
            and None not in window
            and all(w is not None and np.isfinite(w) for w in window)
            and len(set(window)) == 1
        )
    return out
