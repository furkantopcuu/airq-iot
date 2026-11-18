"""RQ1 v0: baselines + LightGBM (k in {0,3,11}) for h in {1,6,24}, evaluated on VALIDATION.

The test split is deliberately NOT touched here (spec 2.4: test is looked at once, at the end).
Early stopping uses the validation set, so the LightGBM validation numbers are slightly
optimistic; they are for model selection and the leakage sanity check only.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from airq.config import config_hash
from airq.data.splits import horizon_mask
from airq.env import resolve_paths
from airq.eval.metrics import improvement_vs_persistence, rmse, summarize
from airq.eval.sanity import sanity_alarms
from airq.features.build import FeatureConfig, build_features, make_target
from airq.features.neighbors import select_neighbors
from airq.models.baselines import RidgeModel, persistence, seasonal_naive
from airq.models.gbm import predict, save_model, train_lgbm
from airq.models.manifest import record_model


def _ks(cfg: dict, n_stations: int) -> list[int]:
    return [k for k in cfg["forecast"]["neighbor_k"] if k == 0 or k <= n_stations - 1]


def run_v0(cfg: dict, quick: bool = False, save_models: bool = True) -> dict:
    paths = resolve_paths(cfg["paths"])
    df = pd.read_parquet(paths["processed"] / "clean.parquet")
    if quick:
        df = df[df["station"].isin(cfg["colab"]["quick"]["stations"])]
    df = df.sort_values(["station", "ts"]).reset_index(drop=True)
    stations = sorted(df["station"].unique())
    ks = _ks(cfg, len(stations))
    cfg_hash = config_hash(cfg)
    train_end = cfg["split"]["train"][1]

    results: dict = {
        "evaluated_on": "val",
        "note": "test split not used; LightGBM early stopping uses val",
        "stations": stations,
        "horizons": {},
    }
    feats_by_k = {}
    for k in ks:
        nbrs = select_neighbors(df, k, train_end) if 0 < k < len(stations) - 1 else None
        feats_by_k[k] = build_features(df, FeatureConfig.from_cfg(cfg, k=k, neighbors=nbrs))

    models_dir = paths["models"]
    rmse_by_h: dict[int, float] = {}
    r2_h24 = None
    t0 = time.time()
    for h in cfg["forecast"]["horizons"]:
        y = make_target(df, h).to_numpy()
        b0, b1 = persistence(df).to_numpy(), seasonal_naive(df, h).to_numpy()
        m_tr = horizon_mask(df["ts"], "train", h, cfg).to_numpy() & ~np.isnan(y)
        m_va = horizon_mask(df["ts"], "val", h, cfg).to_numpy() & ~np.isnan(y)
        ev = m_va & ~np.isnan(b0) & ~np.isnan(b1)  # common rows so every model is compared fairly
        rows = {"n_train": int(m_tr.sum()), "n_val_eval": int(ev.sum()), "models": {}}
        yv = y[ev]
        rows["models"]["B0_persistence"] = summarize(yv, b0[ev])
        rows["models"]["B1_seasonal_naive"] = summarize(yv, b1[ev])

        f0, meta0 = feats_by_k[0]
        ridge = RidgeModel().fit(f0[m_tr], y[m_tr], f0[m_va], y[m_va], meta0.feature_names)
        rows["models"]["B2_ridge_k0"] = {
            **summarize(yv, ridge.predict(f0[ev], meta0.feature_names)),
            "alpha": ridge.alpha_,
        }

        for k in ks:
            feats, meta = feats_by_k[k]
            model = train_lgbm(feats[m_tr], y[m_tr], feats[m_va], y[m_va], meta.feature_names, cfg)
            pred = predict(model, feats[ev], meta.feature_names)
            name = {0: "M1_lgbm_k0"}.get(k, f"M2_lgbm_k{k}")
            summ = summarize(yv, pred)
            summ["best_iteration"] = int(model.best_iteration)
            summ["train_rmse"] = rmse(y[m_tr], predict(model, feats[m_tr], meta.feature_names))
            rows["models"][name] = summ
            if save_models:
                key = f"h{h}_k{k}"
                save_model(model, models_dir / f"lgbm_{key}.txt")
                record_model(models_dir, key, f"lgbm_{key}.txt", meta.feature_names, cfg_hash)

        b0_rmse = rows["models"]["B0_persistence"]["rmse"]
        for m in rows["models"].values():
            m["improvement_vs_b0_pct"] = improvement_vs_persistence(b0_rmse, m["rmse"])
        results["horizons"][str(h)] = rows
        best = min(rows["models"].items(), key=lambda kv: kv[1]["rmse"])
        rmse_by_h[h] = best[1]["rmse"]
        if h == 24:
            r2_h24 = best[1]["r2"]

    results["sanity_alarms"] = sanity_alarms(rmse_by_h, r2_h24, cfg)
    results["runtime_s"] = round(time.time() - t0, 1)
    out = paths["reports"] / "metrics"
    out.mkdir(parents=True, exist_ok=True)
    (out / "forecast_v0.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
