"""RQ1 tuning: Optuna (TPE) hyper-parameter search per (horizon, k) + neighbor ablation.

Protocol (spec 4.3): every LightGBM variant M1 (k=0), M2a (k=3), M2b (k=11) gets the SAME
budget (`optuna_trials`), the search uses the VALIDATION split only, and the study lives in a
SQLite file so an interrupted run resumes where it stopped. The test split is not touched.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import optuna
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

optuna.logging.set_verbosity(optuna.logging.WARNING)

DEFAULT_PARAMS = {
    "num_leaves": 63,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "lambda_l1": 1e-3,
    "lambda_l2": 1.0,
}


def suggest_params(trial: optuna.Trial) -> dict:
    """Search space: the usual LightGBM complexity and regularization knobs."""
    return {
        "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 20, 500, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-3, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 100.0, log=True),
    }


class Data:
    """Cleaned frame, per-k features and per-horizon targets/masks (built once)."""

    def __init__(self, cfg: dict, quick: bool = False):
        paths = resolve_paths(cfg["paths"])
        df = pd.read_parquet(paths["processed"] / "clean.parquet")
        if quick:
            df = df[df["station"].isin(cfg["colab"]["quick"]["stations"])]
        self.df = df.sort_values(["station", "ts"]).reset_index(drop=True)
        self.cfg = cfg
        self.stations = sorted(self.df["station"].unique())
        n = len(self.stations)
        self.ks = [k for k in cfg["forecast"]["neighbor_k"] if k == 0 or k <= n - 1]
        self.feats = {}
        for k in self.ks:
            nbrs = select_neighbors(self.df, k, cfg["split"]["train"][1]) if 0 < k < n - 1 else None
            self.feats[k] = build_features(
                self.df, FeatureConfig.from_cfg(cfg, k=k, neighbors=nbrs)
            )
        self._h: dict[int, dict] = {}

    def horizon(self, h: int) -> dict:
        if h not in self._h:
            y = make_target(self.df, h).to_numpy()
            ok = ~np.isnan(y)
            ts = self.df["ts"]
            b0, b1 = persistence(self.df).to_numpy(), seasonal_naive(self.df, h).to_numpy()
            m_tr = horizon_mask(ts, "train", h, self.cfg).to_numpy() & ok
            m_va = horizon_mask(ts, "val", h, self.cfg).to_numpy() & ok
            self._h[h] = {
                "y": y, "b0": b0, "b1": b1, "m_tr": m_tr, "m_va": m_va,
                "ev": m_va & ~np.isnan(b0) & ~np.isnan(b1),
            }  # fmt: skip
        return self._h[h]


def _storage(models_dir: Path) -> str:
    models_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(models_dir / 'optuna.db').as_posix()}"


def tune_one(data: Data, h: int, k: int, trials: int, models_dir: Path) -> dict:
    """Run (or resume) one study; returns best params, best val RMSE and the default-trial RMSE."""
    cfg = data.cfg
    feats, meta = data.feats[k]
    d = data.horizon(h)
    xtr, ytr = feats[d["m_tr"]], d["y"][d["m_tr"]]
    xva, yva = feats[d["m_va"]], d["y"][d["m_va"]]

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial)
        model = train_lgbm(xtr, ytr, xva, yva, meta.feature_names, cfg, params_override=params)
        trial.set_user_attr("best_iteration", int(model.best_iteration))
        return float(np.sqrt(model.best_score["valid_0"]["l2"]))

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=cfg["project"]["seed"]),
        study_name=f"h{h}_k{k}",
        storage=_storage(models_dir),
        load_if_exists=True,
    )
    if not study.trials:
        study.enqueue_trial(DEFAULT_PARAMS)  # the default config is always evaluated first
    done = sum(t.state == optuna.trial.TrialState.COMPLETE for t in study.trials)
    if done < trials:
        study.optimize(objective, n_trials=trials - done)
    # only the first `trials` trials count, so every study is compared at the same budget even if
    # an earlier run of this study went further
    complete = [
        t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE and t.number < trials
    ]
    best = min(complete, key=lambda t: t.value)
    return {
        "best_params": best.params,
        "best_val_rmse": float(best.value),
        "default_val_rmse": float(complete[0].value),
        "n_trials": len(complete),
        "best_iteration": best.user_attrs.get("best_iteration"),
    }


def run_tuning(
    cfg: dict,
    quick: bool = False,
    trials: int | None = None,
    horizons: list[int] | None = None,
    ks: list[int] | None = None,
) -> dict:
    paths = resolve_paths(cfg["paths"])
    models_dir = paths["models"]
    trials = trials or cfg["forecast"]["optuna_trials"]
    t0 = time.time()
    data = Data(cfg, quick)
    horizons = horizons or cfg["forecast"]["horizons"]
    ks = [k for k in (ks if ks is not None else data.ks) if k in data.ks]
    cfg_hash = config_hash(cfg)
    results: dict = {
        "evaluated_on": "val",
        "note": "Optuna TPE on val; same budget for every k; test split not used",
        "trials_per_study": trials,
        "stations": data.stations,
        "horizons": {},
        "gap_analysis": {},
    }
    tuning_rows = []
    for h in horizons:
        d = data.horizon(h)
        yv = d["y"][d["ev"]]
        rows: dict = {
            "n_train": int(d["m_tr"].sum()),
            "n_val_eval": int(d["ev"].sum()),
            "models": {},
        }
        rows["models"]["B0_persistence"] = summarize(yv, d["b0"][d["ev"]])
        rows["models"]["B1_seasonal_naive"] = summarize(yv, d["b1"][d["ev"]])
        f0, meta0 = data.feats[0]
        ridge = RidgeModel().fit(
            f0[d["m_tr"]], d["y"][d["m_tr"]], f0[d["m_va"]], d["y"][d["m_va"]], meta0.feature_names
        )
        rows["models"]["B2_ridge_k0"] = {
            **summarize(yv, ridge.predict(f0[d["ev"]], meta0.feature_names)),
            "alpha": ridge.alpha_,
        }
        gap = {
            "b0_rmse_train": rmse(d["y"][d["m_tr"] & ~np.isnan(d["b0"])],
                                  d["b0"][d["m_tr"] & ~np.isnan(d["b0"])]),
            "b0_rmse_val": rmse(d["y"][d["m_va"] & ~np.isnan(d["b0"])],
                                d["b0"][d["m_va"] & ~np.isnan(d["b0"])]),
            "models": {},
        }  # fmt: skip
        for k in ks:
            tuned = tune_one(data, h, k, trials, models_dir)
            key = f"h{h}_k{k}"
            (models_dir / f"hparams_{key}.json").write_text(
                json.dumps(tuned, indent=2), encoding="utf-8"
            )
            feats, meta = data.feats[k]
            model = train_lgbm(
                feats[d["m_tr"]], d["y"][d["m_tr"]], feats[d["m_va"]], d["y"][d["m_va"]],
                meta.feature_names, cfg, params_override=tuned["best_params"],
            )  # fmt: skip
            save_model(model, models_dir / f"lgbm_{key}.txt")
            record_model(models_dir, key, f"lgbm_{key}.txt", meta.feature_names, cfg_hash)
            name = "M1_lgbm_k0" if k == 0 else f"M2_lgbm_k{k}"
            summ = summarize(yv, predict(model, feats[d["ev"]], meta.feature_names))
            tr_rmse = rmse(d["y"][d["m_tr"]], predict(model, feats[d["m_tr"]], meta.feature_names))
            summ.update(best_iteration=int(model.best_iteration), train_rmse=tr_rmse)
            rows["models"][name] = summ
            gap["models"][name] = {
                "train_rmse": tr_rmse,
                "val_rmse": float(np.sqrt(model.best_score["valid_0"]["l2"])),
            }
            tuning_rows.append({"h": h, "k": k, **tuned["best_params"],
                                "n_trials": tuned["n_trials"],
                                "default_val_rmse": tuned["default_val_rmse"],
                                "tuned_val_rmse": tuned["best_val_rmse"]})  # fmt: skip
        b0_rmse = rows["models"]["B0_persistence"]["rmse"]
        for m in rows["models"].values():
            m["improvement_vs_b0_pct"] = improvement_vs_persistence(b0_rmse, m["rmse"])
        results["horizons"][str(h)] = rows
        results["gap_analysis"][str(h)] = gap

    best_by_h = {h: min(r["rmse"] for r in v["models"].values()) for h, v in
                 ((int(h), v) for h, v in results["horizons"].items())}  # fmt: skip
    r2_24 = None
    if "24" in results["horizons"]:
        r2_24 = max(m["r2"] for m in results["horizons"]["24"]["models"].values())
    results["sanity_alarms"] = sanity_alarms(best_by_h, r2_24, cfg)
    results["runtime_s"] = round(time.time() - t0, 1)

    metrics, tables = paths["reports"] / "metrics", paths["reports"] / "tables"
    metrics.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    (metrics / "forecast_v1.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    pd.DataFrame(tuning_rows).to_csv(tables / "rq1_tuning.csv", index=False)
    abl = [
        {"h": int(h), "model": name, **{k: v for k, v in m.items() if k != "n"}, "n": m["n"]}
        for h, rows in results["horizons"].items()
        for name, m in rows["models"].items()
    ]
    pd.DataFrame(abl).to_csv(tables / "rq1_ablation_val.csv", index=False)
    return results
