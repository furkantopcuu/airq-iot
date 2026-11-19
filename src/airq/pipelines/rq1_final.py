"""RQ1 final evaluation on the TEST split (looked at ONCE) + LOSO + SHAP (spec 4.4-4.6).

Everything chosen on validation is frozen here: features, tuned hyper-parameters, the saved models.
A guard refuses to re-run unless `force=True`, so test results cannot be tuned against by accident.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from airq.data.splits import horizon_mask
from airq.env import resolve_paths
from airq.eval.metrics import improvement_vs_persistence, mae, r2, rmse, smape
from airq.eval.sanity import sanity_alarms
from airq.eval.stats import block_bootstrap_rmse_diff, dm_test, holm, wilcoxon_paired
from airq.features.build import COPOLL, METEO, FeatureConfig, build_features, make_target
from airq.models.baselines import RidgeModel
from airq.models.gbm import train_lgbm
from airq.models.manifest import load_model_checked
from airq.pipelines.tuning import Data

MODEL_NAMES = {0: "M1_lgbm_k0", 3: "M2_lgbm_k3", 11: "M2_lgbm_k11"}
SEASONS = {
    12: "DJF",
    1: "DJF",
    2: "DJF",
    3: "MAM",
    4: "MAM",
    5: "MAM",
    6: "JJA",
    7: "JJA",
    8: "JJA",
    9: "SON",
    10: "SON",
    11: "SON",
}
GROUP_LABELS = {
    "pm25_lags": "own PM2.5 history",
    "rolling": "own PM2.5 history",
    "copoll_lags": "co-pollutants",
    "meteo": "meteorology",
    "calendar": "calendar",
    "neighbors": "network (neighbors)",
    "quality": "other",
    "station": "other",
}


def _paths(cfg: dict) -> tuple:
    p = resolve_paths(cfg["paths"])
    for d in (p["reports"] / "tables", p["reports"] / "metrics"):
        d.mkdir(parents=True, exist_ok=True)
    return p, p["reports"] / "tables", p["reports"] / "metrics"


def _p95(cfg: dict, data: Data, reports) -> float:
    f = reports / "metrics" / "train_stats.json"
    if f.exists():
        return json.loads(f.read_text())["pm25_p95_train"]
    tr = data.df[(data.df["ts"] <= cfg["split"]["train"][1])]
    return float(tr["pm25_raw"].quantile(cfg["forecast"]["extreme_quantile"]))


def _metrics_row(y, pred) -> dict:
    return {
        "n": len(y),
        "rmse": rmse(y, pred),
        "mae": mae(y, pred),
        "r2": r2(y, pred),
        "smape": smape(y, pred),
        "bias": float(np.mean(np.asarray(y) - np.asarray(pred))),
    }


def _station_rmse(st: np.ndarray, y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {s: rmse(y[st == s], pred[st == s]) for s in sorted(set(st))}


def _compare(ctx: dict, ref: str, mod: str, tag: str) -> tuple[dict, int, int]:
    """Block-bootstrap CI + per-station DM tests (Holm) of `mod` against `ref`."""
    err, stv, stations, h = ctx["err"], ctx["stv"], ctx["stations"], ctx["h"]
    boot = block_bootstrap_rmse_diff(ctx["tsv"], err[ref], err[mod], reps=1000, seed=ctx["seed"])
    tests = [dm_test(err[mod][stv == s], err[ref][stv == s], h) for s in stations]
    adj, rej = holm([q[1] for q in tests])
    for s, (dm, pv), a, r_ in zip(stations, tests, adj, rej, strict=True):
        ctx["rows"].append(
            {
                "h": h,
                "comparison": tag,
                "station": s,
                "dm_stat": dm,
                "p": pv,
                "p_holm": a,
                "significant": bool(r_ and dm < 0),
            }
        )  # a negative DM statistic means `mod` is the more accurate forecast
    n_sig = sum(1 for q, r_ in zip(tests, rej, strict=True) if r_ and q[0] < 0)
    return boot, n_sig, len(stations)


def evaluate_test(cfg: dict, quick: bool = False, force: bool = False) -> dict:
    p, tables, metrics = _paths(cfg)
    guard = metrics / "forecast_test.json"
    if guard.exists() and not force:
        raise FileExistsError(
            f"{guard.name} exists: the test split was already evaluated. "
            "Re-running to chase better test numbers is not allowed (force=True only rebuilds)."
        )
    data = Data(cfg, quick)
    df, ts = data.df, data.df["ts"]
    st_all = df["station"].astype(str).to_numpy()
    p95 = _p95(cfg, data, p["reports"])
    bands = cfg["forecast"]["aqi_bands_pm25"]
    models_dir = p["models"]
    main_rows, abl_rows, stat_rows, ext_rows, brk_rows, stn_rows = [], [], [], [], [], []
    by_h: dict = {}
    for h in cfg["forecast"]["horizons"]:
        d = data.horizon(h)
        y = d["y"]
        m_te = horizon_mask(ts, "test", h, cfg).to_numpy() & ~np.isnan(y)
        ev = m_te & ~np.isnan(d["b0"]) & ~np.isnan(d["b1"])
        f0, meta0 = data.feats[0]
        ridge = RidgeModel().fit(
            f0[d["m_tr"]], y[d["m_tr"]], f0[d["m_va"]], y[d["m_va"]], meta0.feature_names
        )
        preds = {
            "B0_persistence": d["b0"][ev],
            "B1_seasonal_naive": d["b1"][ev],
            "B2_ridge_k0": ridge.predict(f0[ev], meta0.feature_names),
        }
        for k in data.ks:
            feats, meta = data.feats[k]
            booster = load_model_checked(models_dir, f"h{h}_k{k}", meta.feature_names)
            preds[MODEL_NAMES[k]] = booster.predict(feats.loc[ev, meta.feature_names])
        yv, tsv, stv = y[ev], ts[ev].reset_index(drop=True), st_all[ev]
        err = {m: yv - v for m, v in preds.items()}
        b0_rmse = rmse(yv, preds["B0_persistence"])
        stations = sorted(set(stv))
        ctx = {
            "h": h,
            "tsv": tsv,
            "stv": stv,
            "err": err,
            "stations": stations,
            "seed": cfg["project"]["seed"],
            "rows": stat_rows,
        }

        for name, pred in preds.items():
            row = {"h": h, **_metrics_row(yv, pred)}
            row["model"] = name
            row["improvement_vs_b0_pct"] = improvement_vs_persistence(b0_rmse, row["rmse"])
            if name != "B0_persistence":
                boot, n_sig, n_st = _compare(ctx, "B0_persistence", name, f"{name} vs B0")
                row.update(
                    ci_lo=boot["diff_lo"],
                    ci_hi=boot["diff_hi"],
                    pct_ci_lo=boot["pct_lo"],
                    pct_ci_hi=boot["pct_hi"],
                    stations_sig_vs_b0=f"{n_sig}/{n_st}",
                )
            main_rows.append(row)
        m1_rmse = rmse(yv, preds["M1_lgbm_k0"])
        for k in (0, 3, 11):
            if k not in data.ks:
                continue
            name = MODEL_NAMES[k]
            row = {
                "h": h,
                "model": name,
                "rmse": rmse(yv, preds[name]),
                "improvement_vs_b0_pct": improvement_vs_persistence(b0_rmse, rmse(yv, preds[name])),
                "improvement_vs_m1_pct": improvement_vs_persistence(m1_rmse, rmse(yv, preds[name])),
            }
            if k != 0:
                boot, n_sig, n_st = _compare(ctx, "M1_lgbm_k0", name, f"{name} vs M1")
                w_stat, w_p = wilcoxon_paired(
                    np.array(list(_station_rmse(stv, yv, preds[name]).values())),
                    np.array(list(_station_rmse(stv, yv, preds["M1_lgbm_k0"]).values())),
                )
                row.update(
                    ci_lo_vs_m1=boot["diff_lo"],
                    ci_hi_vs_m1=boot["diff_hi"],
                    stations_sig_vs_m1=f"{n_sig}/{n_st}",
                    wilcoxon_p=w_p,
                )
            abl_rows.append(row)
        # per station
        for name, pred in preds.items():
            for s, v in _station_rmse(stv, yv, pred).items():
                stn_rows.append(
                    {
                        "h": h,
                        "model": name,
                        "station": s,
                        "rmse": v,
                        "improvement_vs_b0_pct": improvement_vs_persistence(
                            _station_rmse(stv, yv, preds["B0_persistence"])[s], v
                        ),
                    }
                )
        # extreme subsets (train p95)
        cur = df["pm25_raw"].to_numpy()[ev]
        for label, mask in (
            ("target >= train p95", yv >= p95),
            ("current >= train p95", cur >= p95),
        ):
            if mask.sum() < 5:
                continue
            for name, pred in preds.items():
                ext_rows.append(
                    {
                        "h": h,
                        "subset": label,
                        "p95": p95,
                        "model": name,
                        **_metrics_row(yv[mask], pred[mask]),
                    }
                )
        # breakdowns by season and AQI band of the target
        season = tsv.dt.month.map(SEASONS).to_numpy()
        band = np.digitize(yv, bands)
        for kind, keys in (("season", season), ("aqi_band", band)):
            for key in sorted(set(keys)):
                mk = keys == key
                for name in ("B0_persistence", "M1_lgbm_k0", MODEL_NAMES[max(data.ks)]):
                    brk_rows.append(
                        {
                            "h": h,
                            "kind": kind,
                            "group": str(key),
                            "model": name,
                            "n": int(mk.sum()),
                            "rmse": rmse(yv[mk], preds[name][mk]),
                        }
                    )
        by_h[h] = {
            "best_rmse": min(rmse(yv, v) for v in preds.values()),
            "best_r2": max(r2(yv, v) for v in preds.values()),
        }

    nowcast = _nowcast(data, cfg)
    r2_24 = by_h.get(24, {}).get("best_r2")
    alarms = sanity_alarms({h: v["best_rmse"] for h, v in by_h.items()}, r2_24, cfg)
    pd.DataFrame(main_rows).to_csv(tables / "rq1_main.csv", index=False)
    pd.DataFrame(abl_rows).to_csv(tables / "rq1_ablation.csv", index=False)
    pd.DataFrame(stat_rows).to_csv(tables / "rq1_stats.csv", index=False)
    pd.DataFrame(ext_rows).to_csv(tables / "rq1_extreme.csv", index=False)
    pd.DataFrame(brk_rows).to_csv(tables / "rq1_breakdown.csv", index=False)
    pd.DataFrame(stn_rows).to_csv(tables / "rq1_by_station.csv", index=False)
    pd.DataFrame([nowcast]).to_csv(tables / "rq1_nowcast.csv", index=False)
    summary = {
        "evaluated_on": "test",
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "stations": data.stations,
        "train_p95": p95,
        "by_horizon_best": by_h,
        "nowcast": nowcast,
        "sanity_alarms": alarms,
        "note": "test evaluated once; models, hyper-parameters and main model frozen on validation",
    }
    guard.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _nowcast(data: Data, cfg: dict) -> dict:
    """h=0 control: same-hour PM2.5 from co-pollutants (incl. PM10 at t), meteorology, calendar.

    Shows how high R^2 gets when information from time t is allowed: forecasting claims with
    R^2 ~ 0.99 are usually this nowcast in disguise [R13]. NOT a forecast.
    """
    feats, meta = data.feats[0]
    names = [f"{v}_lag0" for v in COPOLL] + [f"{v}_lag0" for v in METEO]
    names += ["dewp_minus_temp", "station", *meta.groups["calendar"]]
    names = [n for n in names if n in feats.columns]
    y = make_target(data.df, 0).to_numpy()
    ok = ~np.isnan(y)
    ts = data.df["ts"]
    tr = horizon_mask(ts, "train", 0, cfg).to_numpy() & ok
    va = horizon_mask(ts, "val", 0, cfg).to_numpy() & ok
    te = horizon_mask(ts, "test", 0, cfg).to_numpy() & ok
    model = train_lgbm(feats[tr], y[tr], feats[va], y[va], names, cfg)
    pred = model.predict(feats.loc[te, names], num_iteration=model.best_iteration)
    return {"h": 0, "model": "nowcast_lgbm_same_hour", **_metrics_row(y[te], pred)}


def shap_groups(cfg: dict, quick: bool = False, sample: int = 5000, seed: int = 0) -> pd.DataFrame:
    """TreeSHAP (LightGBM pred_contrib) on <= `sample` test rows; shares per feature group [R26]."""
    p, tables, _ = _paths(cfg)
    data = Data(cfg, quick)
    k = max(data.ks)
    feats, meta = data.feats[k]
    group_of = {c: GROUP_LABELS[g] for g, cols in meta.groups.items() for c in cols}
    rows, top = [], []
    rng = np.random.default_rng(seed)
    for h in cfg["forecast"]["horizons"]:
        d = data.horizon(h)
        te = horizon_mask(data.df["ts"], "test", h, cfg).to_numpy() & ~np.isnan(d["y"])
        idx = np.flatnonzero(te)
        idx = rng.choice(idx, size=min(sample, len(idx)), replace=False)
        booster = load_model_checked(p["models"], f"h{h}_k{k}", meta.feature_names)
        contrib = booster.predict(feats.iloc[idx][meta.feature_names], pred_contrib=True)
        mean_abs = np.abs(contrib[:, :-1]).mean(axis=0)  # last column is the bias term
        total = mean_abs.sum()
        share = pd.Series(mean_abs, index=meta.feature_names).groupby(group_of).sum() / total
        for g, v in share.sort_values(ascending=False).items():
            rows.append({"h": h, "k": k, "group": g, "share_pct": 100 * float(v)})
        for f, v in pd.Series(mean_abs, index=meta.feature_names).nlargest(10).items():
            top.append({"h": h, "k": k, "feature": f, "mean_abs_shap": float(v)})
    out = pd.DataFrame(rows)
    out.to_csv(tables / "rq1_shap.csv", index=False)
    pd.DataFrame(top).to_csv(tables / "rq1_shap_top.csv", index=False)
    return out


def loso(cfg: dict, quick: bool = False, force: bool = False) -> pd.DataFrame:
    """Leave-one-station-out: train on 11 stations, test on the held-out one (spec 2.4, 4.4)."""
    p, tables, metrics = _paths(cfg)
    guard = tables / "rq1_loso.csv"
    if guard.exists() and not force:
        raise FileExistsError("rq1_loso.csv exists: LOSO on the test split was already run")
    data = Data(cfg, quick)
    df, ts = data.df, data.df["ts"]
    stations = data.stations
    st_all = df["station"].astype(str).to_numpy()
    main = (
        pd.read_csv(tables / "rq1_by_station.csv")
        if (tables / "rq1_by_station.csv").exists()
        else None
    )
    rows = []
    for s in stations:
        others = [x for x in stations if x != s]
        nbrs = {j: [x for x in others if x != j] for j in others}
        nbrs[s] = others  # the held-out station sees the 11 others; training stations never see it
        fcfg = FeatureConfig.from_cfg(cfg, k=len(others), neighbors=nbrs)
        feats, meta = build_features(df, fcfg)
        names = [c for c in meta.feature_names if c != "station"]  # an unseen station has no id
        for h in cfg["forecast"]["horizons"]:
            d = data.horizon(h)
            y = d["y"]
            hp_file = p["models"] / f"hparams_h{h}_k{max(data.ks)}.json"
            best = json.loads(hp_file.read_text())["best_params"] if hp_file.exists() else {}
            tr = d["m_tr"] & (st_all != s)
            va = d["m_va"] & (st_all != s)
            te = (
                horizon_mask(ts, "test", h, cfg).to_numpy()
                & ~np.isnan(y)
                & ~np.isnan(d["b0"])
                & (st_all == s)
            )
            model = train_lgbm(feats[tr], y[tr], feats[va], y[va], names, cfg, params_override=best)
            pred = model.predict(feats.loc[te, names], num_iteration=model.best_iteration)
            r = rmse(y[te], pred)
            b0 = rmse(y[te], d["b0"][te])
            row = {
                "h": h,
                "station": s,
                "n": int(te.sum()),
                "rmse_loso": r,
                "rmse_b0": b0,
                "improvement_loso_pct": improvement_vs_persistence(b0, r),
            }
            if main is not None:
                ref = main[
                    (main["h"] == h)
                    & (main["station"] == s)
                    & (main["model"] == MODEL_NAMES[max(data.ks)])
                ]
                if len(ref):
                    row["rmse_in_sample_m2"] = float(ref["rmse"].iloc[0])
                    row["improvement_in_sample_pct"] = float(ref["improvement_vs_b0_pct"].iloc[0])
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(guard, index=False)
    return out
