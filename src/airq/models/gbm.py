"""LightGBM point forecasts (M1: k=0, M2a/M2b: k=3/k=11)."""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


def lgbm_params(cfg: dict) -> dict:
    p = dict(cfg["forecast"]["lgbm"])
    for key in ("n_estimators", "early_stopping"):
        p.pop(key)
    p["seed"] = cfg["project"]["seed"]
    p["verbose"] = -1
    return p


def train_lgbm(
    x_tr: pd.DataFrame,
    y_tr: np.ndarray,
    x_va: pd.DataFrame,
    y_va: np.ndarray,
    feature_names: list[str],
    cfg: dict,
    params_override: dict | None = None,
) -> lgb.Booster:
    """Train with early stopping on the validation set (validation is never used for fitting)."""
    f = cfg["forecast"]["lgbm"]
    params = {**lgbm_params(cfg), **(params_override or {})}
    cat = ["station"] if "station" in feature_names else "auto"
    dtr = lgb.Dataset(x_tr[feature_names], y_tr, categorical_feature=cat, free_raw_data=False)
    dva = lgb.Dataset(x_va[feature_names], y_va, categorical_feature=cat, reference=dtr)
    return lgb.train(
        params,
        dtr,
        num_boost_round=f["n_estimators"],
        valid_sets=[dva],
        callbacks=[lgb.early_stopping(f["early_stopping"], verbose=False)],
    )


def predict(model: lgb.Booster, x: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    return model.predict(x[feature_names], num_iteration=model.best_iteration)


def save_model(model: lgb.Booster, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(path), num_iteration=model.best_iteration)  # native text, no pickle
