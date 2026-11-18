"""Baselines B0 (persistence), B1 (seasonal-naive), B2 (Ridge)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def persistence(df: pd.DataFrame) -> pd.Series:
    """B0: y_hat(t+h) = PM2.5(t). `df` is the cleaned frame sorted by (station, ts)."""
    return df["pm25"].reset_index(drop=True)


def seasonal_naive(df: pd.DataFrame, h: int) -> pd.Series:
    """B1: y_hat(t+h) = PM2.5(t+h-24), i.e. the same hour one day earlier (h <= 24)."""
    if not 1 <= h <= 24:
        raise ValueError("seasonal-naive is defined for 1 <= h <= 24")
    return df.groupby("station", sort=True)["pm25"].shift(24 - h).reset_index(drop=True)


def _design(feats: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    num = [c for c in feature_names if c != "station"]
    x = feats[num].astype("float64")
    if "station" in feature_names:
        dummies = pd.get_dummies(feats["station"].astype(str), prefix="st", dtype=float)
        x = pd.concat([x, dummies], axis=1)
    return x


class RidgeModel:
    """B2: median-impute + standardize (fit on train only) + Ridge; alpha chosen on val."""

    def __init__(self, alphas=(0.1, 1.0, 10.0, 100.0, 1000.0)):
        self.alphas = alphas
        self.alpha_: float | None = None
        self.columns_: list[str] | None = None
        self.pipe_ = None

    def fit(self, x_tr, y_tr, x_va, y_va, feature_names: list[str]) -> RidgeModel:
        xtr = _design(x_tr, feature_names)
        self.columns_ = list(xtr.columns)
        xva = _design(x_va, feature_names).reindex(columns=self.columns_, fill_value=0.0)
        best = (np.inf, None, None)
        for a in self.alphas:
            pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=a))
            pipe.fit(xtr, y_tr)
            err = float(np.sqrt(np.mean((y_va - pipe.predict(xva)) ** 2)))
            if err < best[0]:
                best = (err, a, pipe)
        _, self.alpha_, self.pipe_ = best
        return self

    def predict(self, feats: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
        x = _design(feats, feature_names).reindex(columns=self.columns_, fill_value=0.0)
        return self.pipe_.predict(x)
