"""Point-forecast metrics (Appendix B)."""

from __future__ import annotations

import numpy as np


def _arr(a) -> np.ndarray:
    return np.asarray(a, dtype=float)


def rmse(y, yhat) -> float:
    y, yhat = _arr(y), _arr(yhat)
    return float(np.sqrt(np.mean((y - yhat) ** 2)))


def mae(y, yhat) -> float:
    y, yhat = _arr(y), _arr(yhat)
    return float(np.mean(np.abs(y - yhat)))


def r2(y, yhat) -> float:
    y, yhat = _arr(y), _arr(yhat)
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot


def smape(y, yhat, eps: float = 1e-6) -> float:
    y, yhat = _arr(y), _arr(yhat)
    return float(100 * np.mean(2 * np.abs(y - yhat) / (np.abs(y) + np.abs(yhat) + eps)))


def improvement_vs_persistence(rmse_b0: float, rmse_model: float) -> float:
    """Percent RMSE improvement over persistence: 100 * (RMSE_B0 - RMSE_m) / RMSE_B0."""
    return 100.0 * (rmse_b0 - rmse_model) / rmse_b0


def summarize(y, yhat) -> dict[str, float]:
    return {
        "rmse": rmse(y, yhat),
        "mae": mae(y, yhat),
        "r2": r2(y, yhat),
        "smape": smape(y, yhat),
        "n": int(len(_arr(y))),
    }
