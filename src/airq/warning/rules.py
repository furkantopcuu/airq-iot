"""Early-warning rule (spec 5.1): warn at time t for horizon h when  yhat(t+h) > theta - delta_h.

delta_h is a safety margin chosen on VALIDATION by maximising F2 (recall-weighted: a missed
exceedance costs more than a false alarm). Consecutive warnings for one station are merged into
one alert by a cooldown (6 h after an alert opens).
"""

from __future__ import annotations

import numpy as np


def fbeta(precision: float, recall: float, beta: float = 2.0) -> float:
    """F-beta = (1+b^2) P R / (b^2 P + R); 0 when both are 0."""
    denom = beta**2 * precision + recall
    return 0.0 if denom == 0 else float((1 + beta**2) * precision * recall / denom)


def warning_flags(yhat: np.ndarray, theta: float, delta: float) -> np.ndarray:
    """Boolean warning per row. A missing forecast (NaN) never warns."""
    yhat = np.asarray(yhat, dtype=float)
    flags = np.zeros(len(yhat), dtype=bool)
    ok = ~np.isnan(yhat)
    flags[ok] = yhat[ok] > theta - delta
    return flags


def apply_cooldown(flags: np.ndarray, cooldown_h: int) -> np.ndarray:
    """Merge warnings of ONE station (hourly rows, in time order) into alerts.

    After an alert at row i, warnings in rows i+1 .. i+cooldown_h-1 are suppressed; the next alert
    may open at row i+cooldown_h if the warning is still on.
    """
    alerts = np.zeros(len(flags), dtype=bool)
    last = -(10**9)
    for i in np.flatnonzero(flags):
        if i - last >= cooldown_h:
            alerts[i] = True
            last = i
    return alerts


def hourly_scores(y_bool: np.ndarray, flags: np.ndarray) -> tuple[float, float]:
    """(precision, recall) of hourly warnings against 'PM2.5(t+h) > theta'."""
    tp = int(np.sum(flags & y_bool))
    fp = int(np.sum(flags & ~y_bool))
    fn = int(np.sum(~flags & y_bool))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return precision, recall


def select_delta(
    y_bool: np.ndarray, yhat: np.ndarray, theta: float, grid: list[float], beta: float = 2.0
) -> tuple[float, list[dict]]:
    """Pick delta from `grid` maximising F-beta on the given (validation) rows; ties -> smaller."""
    table = []
    for delta in sorted(grid):
        p, r = hourly_scores(y_bool, warning_flags(yhat, theta, delta))
        table.append(
            {"delta": float(delta), "precision": p, "recall": r, "fbeta": fbeta(p, r, beta)}
        )
    best = max(table, key=lambda row: (row["fbeta"], -row["delta"]))
    return best["delta"], table
