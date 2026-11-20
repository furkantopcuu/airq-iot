"""RQ4: forecast uncertainty (quantile models) and q90-based early warning (spec 7).

Protocol (written to docs/KARARLAR.md BEFORE the test split was touched):
- M3 = LightGBM quantile models (alpha 0.1 / 0.5 / 0.9) per horizon, main feature set (k = 11),
  hyper-parameters of the tuned point model of the same horizon (no new search), trained on
  TRAIN, early stopping on VALIDATION pinball loss.
- Interval = [q10, q90] after sorting (no crossing). If the validation coverage is more than 0.03
  off the 0.80 target, ONE widening factor c is fitted on VALIDATION and applied to test as is.
- The test split is evaluated once (guard file `uncertainty_test.json`); nothing is tuned on it.
- Warning comparison: the q90 forecast replaces the point forecast in the RQ2 rule
  (q90 > theta - delta), delta chosen on validation by F2 exactly as for the point forecast; the
  evaluation is `run_rq2` itself (same events, cooldown and metrics), written with tag `rq4`.

Outputs: reports/tables/rq4_{val,coverage,by_station,by_band,calibration,example}.csv plus the
tagged warning tables (rq4_warning, rq4_haze, ...), reports/metrics/uncertainty_test.json,
models/lgbm_q{10,50,90}_h{h}_k{k}.txt and models/quantile_calibration.json (live predictor).
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from airq.config import config_hash
from airq.data.splits import horizon_mask
from airq.env import resolve_paths
from airq.eval.metrics import mean_width, pinball
from airq.models.gbm import predict, save_model
from airq.models.manifest import record_model
from airq.models.quantile import (
    ALPHAS,
    choose_scale,
    interval_coverage,
    rearrange,
    train_quantile,
    widen,
)
from airq.pipelines.rq1_final import MODEL_NAMES, _p95
from airq.pipelines.rq2 import _predictions, run_rq2
from airq.pipelines.tuning import Data

BAND_LABELS = ["<35", "35-75", "75-115", "115-150", "150-250", ">250"]


def _best_params(models_dir, h: int, k: int) -> dict:
    path = models_dir / f"hparams_h{h}_k{k}.json"
    return json.loads(path.read_text(encoding="utf-8"))["best_params"] if path.exists() else {}


def _metrics(y, lo, med, hi, q10, q90) -> dict:
    return {
        "n": int(len(y)),
        "coverage": interval_coverage(y, lo, hi),
        "mean_width": mean_width(lo, hi),
        "pinball_q10": pinball(y, lo, 0.1),
        "pinball_q50": pinball(y, med, 0.5),
        "pinball_q90": pinball(y, hi, 0.9),
        "pinball_q10_raw": pinball(y, q10, 0.1),
        "pinball_q90_raw": pinball(y, q90, 0.9),
    }


def run_uncertainty(cfg: dict, quick: bool = False, force: bool = False) -> dict:
    p = resolve_paths(cfg["paths"])
    tables, metrics = p["reports"] / "tables", p["reports"] / "metrics"
    models_dir = p["models"]
    guard = metrics / "uncertainty_test.json"
    if guard.exists() and not force:
        raise FileExistsError(
            f"{guard.name} exists: the uncertainty models were already evaluated on the test split."
        )
    data = Data(cfg, quick)
    main_k = max(data.ks)
    feats, meta = data.feats[main_k]
    names = meta.feature_names
    df = data.df
    ts_all, st = df["ts"], df["station"].astype(str).to_numpy()
    p95 = _p95(cfg, data, p["reports"])
    bounds = cfg["forecast"]["aqi_bands_pm25"]
    cfg_hash = config_hash(cfg)

    val_rows, cov_rows, st_rows, band_rows, cal_rows = [], [], [], [], []
    scales: dict[str, float] = {}
    q_all: dict[int, dict[str, np.ndarray]] = {}
    for h in cfg["forecast"]["horizons"]:
        d = data.horizon(h)
        y, m_tr, m_va = d["y"], d["m_tr"], d["m_va"]
        m_te = horizon_mask(ts_all, "test", h, cfg).to_numpy() & ~np.isnan(y)
        best = _best_params(models_dir, h, main_k)
        cols = []
        for a in ALPHAS:
            model = train_quantile(feats[m_tr], y[m_tr], feats[m_va], y[m_va], names, cfg, a, best)
            key = f"q{int(round(a * 100))}_h{h}_k{main_k}"
            save_model(model, models_dir / f"lgbm_{key}.txt")
            record_model(models_dir, key, f"lgbm_{key}.txt", names, cfg_hash)
            cols.append(predict(model, feats, names))
        q = rearrange(np.column_stack(cols))
        q10, q50, q90 = q[:, 0], q[:, 1], q[:, 2]
        c, info = choose_scale(y[m_va], q10[m_va], q50[m_va], q90[m_va])
        scales[str(h)] = c
        cal_rows.append({"h": h, "c": c, **info})
        lo_c, hi_c = widen(q10, q50, q90, c)
        lo_r, hi_r = widen(q10, q50, q90, 1.0)
        q_all[h] = {"q10": q10, "q50": q50, "q90": q90, "lo": lo_c, "hi": hi_c}
        variants = {"raw": (lo_r, hi_r), "calibrated": (lo_c, hi_c)}
        for variant, (lo, hi) in variants.items():
            val_rows.append(
                {"h": h, "variant": variant, "c": c if variant == "calibrated" else 1.0,
                 **_metrics(y[m_va], lo[m_va], q50[m_va], hi[m_va], q10[m_va], q90[m_va])}
            )  # fmt: skip
            for subset, mask in (("all", m_te), ("target >= train p95", m_te & (y >= p95))):
                cov_rows.append(
                    {"h": h, "variant": variant, "subset": subset,
                     "c": c if variant == "calibrated" else 1.0,
                     **_metrics(y[mask], lo[mask], q50[mask], hi[mask], q10[mask], q90[mask])}
                )  # fmt: skip
            for s in sorted(set(st)):
                mask = m_te & (st == s)
                st_rows.append(
                    {"h": h, "variant": variant, "station": s,
                     "coverage": interval_coverage(y[mask], lo[mask], hi[mask]),
                     "mean_width": mean_width(lo[mask], hi[mask]), "n": int(mask.sum())}
                )  # fmt: skip
            band = np.digitize(np.nan_to_num(y, nan=-1.0), bounds)
            for b, label in enumerate(BAND_LABELS):
                mask = m_te & (band == b)
                if mask.sum() == 0:
                    continue
                band_rows.append(
                    {"h": h, "variant": variant, "band": label,
                     "coverage": interval_coverage(y[mask], lo[mask], hi[mask]),
                     "mean_width": mean_width(lo[mask], hi[mask]), "n": int(mask.sum())}
                )  # fmt: skip

    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "quantile_calibration.json").write_text(
        json.dumps({"k": main_k, "c": scales, "alphas": list(ALPHAS)}, indent=2), encoding="utf-8"
    )
    tables.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(val_rows).to_csv(tables / "rq4_val.csv", index=False)
    pd.DataFrame(cov_rows).to_csv(tables / "rq4_coverage.csv", index=False)
    pd.DataFrame(st_rows).to_csv(tables / "rq4_by_station.csv", index=False)
    pd.DataFrame(band_rows).to_csv(tables / "rq4_by_band.csv", index=False)
    pd.DataFrame(cal_rows).to_csv(tables / "rq4_calibration.csv", index=False)
    _example(cfg, data, q_all, p, tables)

    # q90-based warning vs the point forecast: the RQ2 evaluation itself, tagged "rq4"
    point = _predictions(data, models_dir)
    main_name = MODEL_NAMES[main_k]
    methods = {
        "B0_persistence": point["B0_persistence"],
        main_name: point[main_name],
        "M3_q90_raw": {h: widen(v["q10"], v["q50"], v["q90"], 1.0)[1] for h, v in q_all.items()},
        "M3_q90_cal": {h: v["hi"] for h, v in q_all.items()},
    }
    warn = run_rq2(cfg, quick, force, methods_override=methods, tag="rq4")

    summary = {
        "evaluated_on": "test",
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "k": main_k,
        "scales": scales,
        "target_coverage": 0.8,
        "train_p95": p95,
        "warning_methods": list(methods),
        "note": "protocol fixed in docs/KARARLAR.md before the test run; c fitted on validation",
        "warning": {k: v for k, v in warn.items() if k in ("n_test_exceedance_events",)},
    }
    guard.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _example(cfg: dict, data: Data, q_all: dict, p: dict, tables) -> None:
    """One station through the largest test regional haze at h = 6: observation, point forecast and
    the calibrated interval (input of the RQ4 figure)."""
    ep = pd.read_csv(tables / "episodes_test.csv", parse_dates=["start", "end"])
    haze = ep[ep["type"] == "regional_haze"].sort_values(["hours", "peak"], ascending=False)
    if haze.empty or 6 not in q_all:
        return
    onset = haze.iloc[0]["start"]
    st = "Dongsi" if "Dongsi" in set(data.df["station"]) else data.stations[0]
    mask = (
        (data.df["station"] == st)
        & (data.df["ts"] >= onset - pd.Timedelta(hours=48))
        & (data.df["ts"] <= onset + pd.Timedelta(hours=72))
    ).to_numpy()
    point = _predictions(data, p["models"])[MODEL_NAMES[max(data.ks)]][6]
    q = q_all[6]
    ts = data.df["ts"].to_numpy()
    out = pd.DataFrame(
        {
            "target_ts": ts[mask] + np.timedelta64(6, "h"),  # forecasts made at ts are for ts + 6 h
            "made_at_ts": ts[mask],
            "station": st,
            "yhat_point": point[mask],
            "q10": q["lo"][mask],
            "q50": q["q50"][mask],
            "q90": q["hi"][mask],
        }
    )
    truth = data.df.set_index(["station", "ts"])["pm25_raw"]
    out["obs_at_target"] = [truth.get((st, pd.Timestamp(t)), np.nan) for t in out["target_ts"]]
    out.to_csv(tables / "rq4_example.csv", index=False)
