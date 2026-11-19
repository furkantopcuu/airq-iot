"""RQ2: early warning from forecasts. delta_h is chosen on VALIDATION, applied to TEST once.

Methods compared: persistence (B0), seasonal-naive (B1), M1 (no neighbors) and the main model M2
(k=11). Every method gets its own delta from the same validation procedure (F2), so the comparison
is fair. Outputs (reports/tables): rq2_warning, rq2_haze, rq2_delta_val, rq2_lead_hist,
rq2_pr_curve, rq2_example; reports/metrics: warning_test.json, warning_thresholds.json.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve

from airq.data.splits import horizon_mask
from airq.env import resolve_paths
from airq.features.build import make_target
from airq.models.baselines import persistence, seasonal_naive
from airq.models.manifest import load_model_checked
from airq.pipelines.rq1_final import MODEL_NAMES
from airq.pipelines.tuning import Data
from airq.warning.evaluate import (
    combine_any,
    event_leads,
    false_alarm_stats,
    hourly_metrics,
    matched_leads,
    summarize_leads,
)
from airq.warning.rules import apply_cooldown, select_delta, warning_flags


def _predictions(data: Data, models_dir) -> dict[str, dict[int, np.ndarray]]:
    """yhat(t+h) for every row and horizon, per method (NaN where a model cannot forecast)."""
    cfg = data.cfg
    preds: dict[str, dict[int, np.ndarray]] = {}
    main_k = max(data.ks)
    names = {"B0_persistence": None, "B1_seasonal_naive": None, "M1_lgbm_k0": 0}
    if main_k != 0:
        names[MODEL_NAMES[main_k]] = main_k
    for m, k in names.items():
        preds[m] = {}
        for h in cfg["forecast"]["horizons"]:
            if m == "B0_persistence":
                preds[m][h] = persistence(data.df).to_numpy(dtype=float)
            elif m == "B1_seasonal_naive":
                preds[m][h] = seasonal_naive(data.df, h).to_numpy(dtype=float)
            else:
                feats, meta = data.feats[k]
                booster = load_model_checked(models_dir, f"h{h}_k{k}", meta.feature_names)
                preds[m][h] = booster.predict(feats[meta.feature_names])
    return preds


def run_rq2(cfg: dict, quick: bool = False, force: bool = False) -> dict:
    p = resolve_paths(cfg["paths"])
    tables, metrics = p["reports"] / "tables", p["reports"] / "metrics"
    guard = metrics / "warning_test.json"
    if guard.exists() and not force:
        raise FileExistsError(
            f"{guard.name} exists: the warning system was already evaluated on the test split."
        )
    w = cfg["warning"]
    data = Data(cfg, quick)
    df, ts_all = data.df, data.df["ts"]
    ts_np = ts_all.to_numpy()
    obs = df["pm25_raw"].to_numpy(dtype=float)
    st = df["station"].astype(str).to_numpy()
    starts = np.flatnonzero(np.r_[True, st[1:] != st[:-1]])
    bounds = {st[a]: (a, b) for a, b in zip(starts, np.r_[starts[1:], len(st)], strict=True)}
    test_start = np.datetime64(pd.Timestamp(cfg["split"]["test"][0]), "ns")
    preds = _predictions(data, p["models"])
    methods = list(preds)
    horizons = cfg["forecast"]["horizons"]
    ep = pd.read_csv(tables / "episodes_test.csv", parse_dates=["start", "end"])
    in_test = ts_np >= test_start

    spec_grid = sorted(w["delta_grid"])
    # "wide" is a SUPERSET of the specified grid, so it can never choose a worse val delta
    grids = {"spec": spec_grid, "wide": sorted(set(spec_grid) | set(range(0, 101, 10)))}
    rows, haze_rows, delta_rows, hist_rows, thresholds = [], [], [], [], {}
    pr_curve_rows, alert_store, matched_by_h = [], {}, {}
    for grid_name, grid, theta in [(g, grids[g], t) for g in grids for t in w["thresholds"]]:
        events = ep[(ep["type"] == "exceedance") & (ep["threshold"] == theta)]
        for m in methods:
            any_alert = np.zeros(len(df), dtype=bool)
            for h in horizons:
                y = make_target(df, h).to_numpy()
                ok = ~np.isnan(y)
                m_va = horizon_mask(ts_all, "val", h, cfg).to_numpy() & ok
                m_te = horizon_mask(ts_all, "test", h, cfg).to_numpy() & ok
                yhat = preds[m][h]
                delta, table = select_delta(y[m_va] > theta, yhat[m_va], theta, grid, w["beta"])
                for t in table:
                    delta_rows.append(
                        {"grid": grid_name, "method": m, "theta": theta, "h": h, **t,
                         "chosen": t["delta"] == delta}
                    )  # fmt: skip
                thresholds.setdefault(grid_name, {}).setdefault(m, {}).setdefault(str(theta), {})[
                    str(h)
                ] = delta
                hm = hourly_metrics(y[m_te] > theta, yhat[m_te], theta, delta)
                flags = warning_flags(yhat, theta, delta)
                alert = np.zeros(len(df), dtype=bool)
                for a, b in bounds.values():
                    alert[a:b] = apply_cooldown(flags[a:b], w["cooldown_h"])
                any_alert |= alert
                row = {
                    "grid": grid_name,
                    "method": m,
                    "theta": theta,
                    "h": str(h),
                    "delta": delta,
                    **hm,
                }
                cols, matched = _event_columns(
                    events,
                    alert,
                    ts_np,
                    bounds,
                    obs,
                    theta,
                    in_test,
                    w,
                    hist_rows,
                    m,
                    f"{grid_name}:{h}",
                    h,
                )
                row.update(cols)
                matched_by_h[(grid_name, m, theta, h)] = matched
                row.update(_matched_columns(matched))
                rows.append(row)
                alert_store[(grid_name, m, theta, h)] = alert
                if (
                    grid_name == "spec"
                    and theta == 150
                    and h == 6
                    and m in ("B0_persistence", "M1_lgbm_k0", MODEL_NAMES.get(max(data.ks), ""))
                ):
                    prec, rec, _ = precision_recall_curve(
                        y[m_te] > theta, np.nan_to_num(yhat[m_te], nan=-1e9)
                    )
                    idx = np.unique(np.linspace(0, len(prec) - 1, 300).astype(int))
                    pr_curve_rows += [
                        {"method": m, "precision": float(prec[i]), "recall": float(rec[i])}
                        for i in idx
                    ]
            row = {"grid": grid_name, "method": m, "theta": theta, "h": "any", "delta": np.nan}
            cols, _ = _event_columns(
                events,
                any_alert,
                ts_np,
                bounds,
                obs,
                theta,
                in_test,
                w,
                hist_rows,
                m,
                f"{grid_name}:any",
                None,
            )
            row.update(cols)
            any_matched = combine_any([matched_by_h[(grid_name, m, theta, h)] for h in horizons])
            row.update(_matched_columns(any_matched))
            _hist(hist_rows, m, f"{grid_name}:any", "matched", any_matched, w["window_h"], theta)
            rows.append(row)
            alert_store[(grid_name, m, theta, "any")] = any_alert
    # regional haze episodes (theta = 150, any station alerting counts)
    haze = ep[ep["type"] == "regional_haze"]
    haze_matched: dict[tuple, list] = {}
    for grid_name, m in [(g, m) for g in grids for m in methods]:
        for h in [*horizons, "any"]:
            alert = alert_store[(grid_name, m, 150, h)]
            times = ts_np[alert]
            leads = event_leads(haze["start"], times, w["window_h"])
            s = summarize_leads(leads)
            if h == "any":
                matched = combine_any(haze_matched[(grid_name, m)])
            else:
                matched = matched_leads(haze["start"], haze["end"], times, h, w["window_h"])
                haze_matched.setdefault((grid_name, m), []).append(matched)
            s.update(_matched_columns(matched))
            frac = []
            for onset in haze["start"]:
                lo, hi = (
                    np.datetime64(onset - pd.Timedelta(hours=w["window_h"]), "ns"),
                    np.datetime64(onset, "ns"),
                )
                hit = {st[i] for i in np.flatnonzero(alert & (ts_np >= lo) & (ts_np <= hi))}
                frac.append(len(hit) / len(bounds))
            haze_rows.append(
                {
                    "grid": grid_name,
                    "method": m,
                    "h": str(h),
                    **s,
                    "mean_station_fraction_warned": float(np.mean(frac)) if frac else np.nan,
                }
            )

    example = _example(data, preds, alert_store, haze, bounds, ts_np, obs, st, cfg)
    pd.DataFrame(rows).to_csv(tables / "rq2_warning.csv", index=False)
    pd.DataFrame(haze_rows).to_csv(tables / "rq2_haze.csv", index=False)
    pd.DataFrame(delta_rows).to_csv(tables / "rq2_delta_val.csv", index=False)
    pd.DataFrame(hist_rows).to_csv(tables / "rq2_lead_hist.csv", index=False)
    pd.DataFrame(pr_curve_rows).to_csv(tables / "rq2_pr_curve.csv", index=False)
    if example is not None:
        example[0].to_csv(tables / "rq2_example.csv", index=False)
    (metrics / "warning_thresholds.json").write_text(
        json.dumps(thresholds, indent=2), encoding="utf-8"
    )
    p["models"].mkdir(parents=True, exist_ok=True)
    (p["models"] / "warning_thresholds.json").write_text(
        json.dumps(thresholds, indent=2), encoding="utf-8"
    )
    summary = {
        "evaluated_on": "test",
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "methods": methods,
        "n_test_exceedance_events": {
            str(t): int(((ep["type"] == "exceedance") & (ep["threshold"] == t)).sum())
            for t in w["thresholds"]
        },
        "n_test_regional_haze": int(len(haze)),
        "example": example[1] if example is not None else None,
        "grids": {k: v for k, v in grids.items()},
        "note": "delta chosen on validation (F2); grid spec = as specified, wide = sensitivity",
    }
    guard.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _matched_columns(matched: list[float | None]) -> dict:
    """Event recall and lead-time quartiles under the horizon-matched definition."""
    s = summarize_leads(matched)
    return {
        "m_event_recall": s["event_recall"],
        "m_lead_median": s["lead_median"],
        "m_lead_q25": s["lead_q25"],
        "m_lead_q75": s["lead_q75"],
    }


def _hist(hist_rows, method, label, kind, leads, window_h, theta):
    caught = np.array([x for x in leads if x is not None])
    for lo in range(0, window_h + 1):
        hist_rows.append(
            {"method": method, "theta": theta, "h": label, "kind": kind, "lead_h": lo,
             "count": int(np.sum(caught == lo)) if len(caught) else 0}
        )  # fmt: skip


def _event_columns(
    events, alert, ts_np, bounds, obs, theta, in_test, w, hist_rows, method, label, hz
):
    """Event metrics for one alert series: the spec definition (any alert in the 24 h before the
    onset) and, when `hz` is given, the horizon-matched leads (returned for the union over h)."""
    window_h = w["window_h"]
    leads, matched = [], []
    for s, (a, b) in bounds.items():
        sub = events.loc[events["station"] == s]
        times = ts_np[a:b][alert[a:b]]
        leads += event_leads(sub["start"], times, window_h)
        if hz is not None:
            matched += matched_leads(sub["start"], sub["end"], times, hz, window_h)
    out = summarize_leads(leads)
    _hist(hist_rows, method, label, "spec", leads, window_h, theta)
    if hz is not None:
        _hist(hist_rows, method, label, "matched", matched, window_h, theta)
    fa = tot = 0
    for a, b in bounds.values():
        idx = np.flatnonzero(alert[a:b] & in_test[a:b])
        f, t = false_alarm_stats(idx, obs[a:b], theta)
        fa, tot = fa + f, tot + t
    out.update(n_alerts=tot, false_alarm_rate=(fa / tot) if tot else float("nan"))
    return out, matched


def _example(data, preds, alert_store, haze, bounds, ts_np, obs, st, cfg):
    """Series around the LARGEST test regional haze (rule fixed in advance, not cherry-picked)."""
    if haze.empty:
        return None
    ep = haze.sort_values(["hours", "peak"], ascending=False).iloc[0]
    station = "Dongsi" if "Dongsi" in bounds else sorted(bounds)[0]
    a, b = bounds[station]
    main = MODEL_NAMES.get(max(data.ks), "M1_lgbm_k0")
    lo, hi = ep["start"] - pd.Timedelta(hours=72), ep["start"] + pd.Timedelta(hours=48)
    ts_s = pd.to_datetime(ts_np[a:b])
    sel = (ts_s >= lo) & (ts_s <= hi)
    out = pd.DataFrame({"ts": ts_s[sel], "y_obs": obs[a:b][sel]})
    meta = {
        "station": station,
        "onset": str(ep["start"]),
        "hours": int(ep["hours"]),
        "peak": float(ep["peak"]),
        "model": main,
    }
    for h in (6, 24):
        shifted = np.full(b - a, np.nan)
        shifted[h:] = preds[main][h][a:b][
            : (b - a) - h
        ]  # forecast made h hours earlier, aligned to its target hour
        out[f"yhat_h{h}"] = shifted[sel]
        alert = alert_store[("wide", main, 150, h)][a:b]
        out[f"alert_h{h}"] = alert[sel]
        lead = matched_leads(
            pd.Series([ep["start"]]), pd.Series([ep["end"]]), ts_s[alert].to_numpy(), h,
            cfg["warning"]["window_h"],
        )  # fmt: skip
        meta[f"lead_h{h}"] = lead[0]
    return out, meta
