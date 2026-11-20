"""M3: LightGBM quantile forecasts and a split-conformal-style interval calibration (RQ4, spec 7).

Quantile regression with the pinball loss follows Koenker & Bassett; LightGBM supports it natively
(`objective=quantile`, `alpha`). The hyper-parameters are those tuned for the point model of the
same horizon (no extra search budget). Quantile crossing is removed by sorting the three
predictions of each row (rearrangement, Chernozhukov et al. 2010). If the validation coverage of
the [q10, q90] interval is clearly off target, a single widening factor `c` is fitted on VALIDATION
(a simplified conformal / CQR-style correction in the spirit of Romano et al. 2019).
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from airq.models.gbm import train_lgbm

ALPHAS = (0.1, 0.5, 0.9)
TARGET_COVERAGE = 0.80  # nominal coverage of [q10, q90]
TOLERANCE = 0.03  # "clearly off target": |validation coverage - 0.80| > 0.03
C_GRID = tuple(np.round(np.arange(0.5, 3.0001, 0.05), 2))


def quantile_params(alpha: float, best_params: dict | None) -> dict:
    return {**(best_params or {}), "objective": "quantile", "alpha": alpha, "metric": "quantile"}


def train_quantile(
    x_tr: pd.DataFrame,
    y_tr: np.ndarray,
    x_va: pd.DataFrame,
    y_va: np.ndarray,
    feature_names: list[str],
    cfg: dict,
    alpha: float,
    best_params: dict | None = None,
) -> lgb.Booster:
    """Train one quantile model; early stopping uses the validation pinball loss only."""
    return train_lgbm(
        x_tr,
        y_tr,
        x_va,
        y_va,
        feature_names,
        cfg,
        params_override=quantile_params(alpha, best_params),
    )


def rearrange(q: np.ndarray) -> np.ndarray:
    """Make each row non-decreasing (q10 <= q50 <= q90); NaN rows stay NaN."""
    return np.sort(q, axis=1)


def widen(q10: np.ndarray, q50: np.ndarray, q90: np.ndarray, c: float):
    """Scale the interval around the median by `c` (c = 1 leaves it unchanged); PM2.5 >= 0."""
    lo = np.maximum(q50 - c * (q50 - q10), 0.0)
    hi = np.maximum(q50 + c * (q90 - q50), 0.0)
    return lo, hi


def interval_coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(hi))
    return float(np.mean((y[ok] >= lo[ok]) & (y[ok] <= hi[ok]))) if ok.any() else float("nan")


def choose_scale(
    y: np.ndarray,
    q10: np.ndarray,
    q50: np.ndarray,
    q90: np.ndarray,
    target: float = TARGET_COVERAGE,
    tolerance: float = TOLERANCE,
    grid: tuple = C_GRID,
) -> tuple[float, dict]:
    """Fit the widening factor on VALIDATION data only.

    Returns (c, info). c = 1.0 when the raw coverage is already within `tolerance` of `target`.
    Otherwise the grid value whose coverage is closest to the target is taken (smallest c on ties).
    """
    raw = interval_coverage(y, *widen(q10, q50, q90, 1.0))
    info = {"coverage_raw_val": raw, "target": target, "tolerance": tolerance}
    if abs(raw - target) <= tolerance:
        return 1.0, {**info, "calibrated": False, "coverage_cal_val": raw}
    best_c, best_gap, best_cov = 1.0, abs(raw - target), raw
    for c in grid:
        cov = interval_coverage(y, *widen(q10, q50, q90, float(c)))
        gap = abs(cov - target)
        if gap < best_gap - 1e-12:
            best_c, best_gap, best_cov = float(c), gap, cov
    return best_c, {**info, "calibrated": True, "coverage_cal_val": best_cov}
