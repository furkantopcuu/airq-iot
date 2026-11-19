"""RQ3b: how much does faulty sensor INPUT hurt the forecast, and how much does the edge recover?

Three conditions on the TEST inputs (targets are never touched), frozen models, 5 seeds:
  clean     - the recorded data
  edge_off  - PM2.5 inputs corrupted (spike / stuck / dropout), passed through unchecked
  edge_on   - same corruption, but values flagged by the edge rules are replaced by null
              (then the usual past-only ffill), exactly what the live edge does with filter ON.
Reports RMSE (all rows, rows whose last 24 h of input contain a fault, per fault type) and the
warning F2 per condition, plus how many injected fault hours the edge rules catch.
The faults are synthetic: this measures forecast robustness, NOT fault-detection quality.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from airq.data.clean import clean
from airq.data.load import load_raw
from airq.data.splits import horizon_mask
from airq.edge.quality import VALUE_FLAGS, flag_frame
from airq.env import resolve_paths
from airq.eval.metrics import rmse
from airq.features.build import FeatureConfig, build_features, make_target
from airq.features.neighbors import select_neighbors
from airq.models.manifest import load_model_checked
from airq.perturb.inject import TYPE_CODE, inject, robust_sigma
from airq.pipelines.data import _find_csv_dir
from airq.pipelines.edge import load_params
from airq.pipelines.rq1_final import MODEL_NAMES
from airq.warning.rules import fbeta, hourly_scores, warning_flags

CONDITIONS = ("clean", "edge_off", "edge_on")
CODE_NAME = {v: k for k, v in TYPE_CODE.items()}


def _blocks(station: np.ndarray) -> list[tuple[int, int]]:
    starts = np.flatnonzero(np.r_[True, station[1:] != station[:-1]])
    return list(zip(starts, np.r_[starts[1:], len(station)], strict=True))


def _last_fault(mask: np.ndarray, blocks, window: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """For every row: is a corrupted hour inside its last `window` hours, and of which type?"""
    affected = np.zeros(len(mask), dtype=bool)
    kind = np.zeros(len(mask), dtype=np.int8)
    for a, b in blocks:
        m = mask[a:b]
        idx = np.where(m > 0, np.arange(b - a), -1)
        last = np.maximum.accumulate(idx)
        ok = (last >= 0) & (np.arange(b - a) - last < window)
        affected[a:b] = ok
        kind[a:b] = np.where(ok, m[np.clip(last, 0, None)], 0)
    return affected, kind


class _Predictor:
    """Frozen models for one condition: features -> predictions for the test rows."""

    def __init__(self, cfg: dict, models_dir, ks: list[int], neighbors: dict):
        self.cfg, self.models_dir, self.ks, self.neighbors = cfg, models_dir, ks, neighbors
        self._boosters: dict = {}

    def predict(self, df: pd.DataFrame, rows: np.ndarray) -> dict[str, dict[int, np.ndarray]]:
        out: dict[str, dict[int, np.ndarray]] = {"B0_persistence": {}}
        for h in self.cfg["forecast"]["horizons"]:
            out["B0_persistence"][h] = df["pm25"].to_numpy(dtype=float)[rows]
        for k in self.ks:
            fcfg = FeatureConfig.from_cfg(self.cfg, k=k, neighbors=self.neighbors.get(k))
            feats, meta = build_features(df, fcfg)
            name = "M1_lgbm_k0" if k == 0 else MODEL_NAMES[k]
            out[name] = {}
            for h in self.cfg["forecast"]["horizons"]:
                key = (k, h)
                if key not in self._boosters:
                    self._boosters[key] = load_model_checked(
                        self.models_dir, f"h{h}_k{k}", meta.feature_names
                    )
                x = feats.iloc[rows][meta.feature_names]
                out[name][h] = self._boosters[key].predict(x)
        return out


def run_rq3b(
    cfg: dict, quick: bool = False, seeds: list[int] | None = None, force: bool = False
) -> dict:
    p = resolve_paths(cfg["paths"])
    tables, metrics = p["reports"] / "tables", p["reports"] / "metrics"
    tables.mkdir(parents=True, exist_ok=True)
    metrics.mkdir(parents=True, exist_ok=True)
    guard = metrics / "rq3b_test.json"
    if guard.exists() and not force:
        raise FileExistsError(f"{guard.name} exists: RQ3b was already run on the test inputs.")
    seeds = list(cfg["perturb"]["seeds"]) if seeds is None else seeds
    horizons = cfg["forecast"]["horizons"]
    stations_cfg = cfg["colab"]["quick"]["stations"] if quick else cfg["data"]["stations"]

    raw = load_raw(_find_csv_dir(p["raw"]))
    raw = (
        raw[raw["station"].isin(stations_cfg)].sort_values(["station", "ts"]).reset_index(drop=True)
    )
    start, end = cfg["split"]["train"][0], cfg["split"]["test"][1]
    clean_df = clean(raw, start, end, cfg["data"]["ffill_limit"])
    ts = clean_df["ts"]
    st = clean_df["station"].astype(str).to_numpy()
    blocks = _blocks(st)
    n_st = len(blocks)
    test_lo = np.datetime64(pd.Timestamp(cfg["split"]["test"][0]), "ns")
    train_hi = np.datetime64(pd.Timestamp(cfg["split"]["train"][1]), "ns")
    in_test = ts.to_numpy() >= test_lo
    base = clean_df["pm25_raw"].to_numpy(dtype=float)
    sigma = {
        st[a]: robust_sigma(base[a:b][ts.to_numpy()[a:b] <= train_hi]) for a, b in blocks
    }  # fit on TRAIN only
    params = load_params(cfg)
    ks = [0] + (
        [max(k for k in cfg["forecast"]["neighbor_k"] if k <= n_st - 1)] if n_st > 1 else []
    )
    ks = sorted(set(ks))
    neighbors = {
        k: (select_neighbors(clean_df, k, cfg["split"]["train"][1]) if 0 < k < n_st - 1 else None)
        for k in ks
    }
    thresholds = json.loads((p["models"] / "warning_thresholds.json").read_text())["spec"]
    pred = _Predictor(cfg, p["models"], ks, neighbors)
    rows_te = np.flatnonzero(in_test)

    # rows evaluated per horizon: test rows with an observed target and a clean persistence value
    ev, y_ev = {}, {}
    for h in horizons:
        y = make_target(clean_df, h).to_numpy()
        ok = (
            horizon_mask(ts, "test", h, cfg).to_numpy()
            & ~np.isnan(y)
            & ~np.isnan(clean_df["pm25"].to_numpy())
        )
        ev[h], y_ev[h] = ok[rows_te], y[rows_te]
    clean_preds = pred.predict(clean_df, rows_te)
    methods = list(clean_preds)

    acc: dict = {}  # (method, h, condition, scope) -> list of per-seed values
    f2acc: dict = {}  # (method, h, condition, theta) -> list of (precision, recall, f2)
    cover: dict = {}  # (condition) -> persistence coverage per seed
    det_rows: list[dict] = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        pert = base.copy()
        mask = np.zeros(len(base), dtype=np.int8)
        for a, b in blocks:
            lo = int(np.searchsorted(ts.to_numpy()[a:b], test_lo))
            series, m, _ = inject(base[a:b], sigma[st[a]], cfg["perturb"], rng, lo, b - a)
            pert[a:b], mask[a:b] = series, m
        # corrupted raw -> cleaned (edge off)
        raw_pert = raw.copy()
        for a, b in blocks:
            s_ts = clean_df["ts"].iloc[a:b]
            raw_pert.loc[raw_pert["station"] == st[a], "pm25"] = (
                pd.Series(pert[a:b], index=s_ts)
                .reindex(raw_pert.loc[raw_pert["station"] == st[a], "ts"])
                .to_numpy()
            )
        off_df = clean(raw_pert, start, end, cfg["data"]["ffill_limit"])
        flags = flag_frame(off_df, params)  # edge rules on the corrupted stream
        bad = flags[list(VALUE_FLAGS)].any(axis=1).to_numpy()
        raw_on = raw_pert.copy()
        key = off_df[["station", "ts"]].assign(_bad=bad)
        raw_on = raw_on.merge(key, on=["station", "ts"], how="left")
        raw_on.loc[raw_on["_bad"].fillna(False).astype(bool), "pm25"] = np.nan
        on_df = clean(raw_on.drop(columns="_bad"), start, end, cfg["data"]["ffill_limit"])
        affected, kind = _last_fault(mask, blocks)
        aff_te, kind_te = affected[rows_te], kind[rows_te]
        # detection of injected faults by the edge value rules (hour level and segment level)
        for code, name in CODE_NAME.items():
            sel = mask == code
            seg_hit = 0
            seg_total = 0
            for a, b in blocks:
                m = mask[a:b]
                starts_ = np.flatnonzero((m == code) & np.r_[True, m[:-1] != code])
                for s0 in starts_:
                    e0 = s0
                    while e0 < len(m) and m[e0] == code:
                        e0 += 1
                    seg_total += 1
                    seg_hit += int(bad[a + s0 : a + e0].any())
            det_rows.append({"seed": seed, "type": name, "hours": int(sel.sum()),
                             "hours_flagged": int(bad[sel].sum()), "segments": seg_total,
                             "segments_detected": seg_hit})  # fmt: skip
        clean_obs = in_test & (mask == 0) & ~np.isnan(base)
        det_rows.append({"seed": seed, "type": "clean_test_hours", "hours": int(clean_obs.sum()),
                         "hours_flagged": int(bad[clean_obs].sum()), "segments": 0,
                         "segments_detected": 0})  # fmt: skip

        for cond, dfc in (("edge_off", off_df), ("edge_on", on_df)):
            preds = pred.predict(dfc, rows_te)
            for m in methods:
                for h in horizons:
                    for c2, source in (("clean", clean_preds), (cond, preds)):
                        yhat = source[m][h]
                        okp = ev[h] & ~np.isnan(yhat)
                        scopes = [("all", okp), ("affected", okp & aff_te)]
                        scopes += [(n, okp & (kind_te == c)) for c, n in CODE_NAME.items()]
                        for scope, sel in scopes:
                            if sel.sum() >= 5:
                                acc.setdefault(
                                    (m, h, c2 if c2 == "clean" else cond, scope), []
                                ).append((seed, rmse(y_ev[h][sel], yhat[sel]), int(sel.sum())))
                        if m == "B0_persistence":
                            cover.setdefault((cond if c2 != "clean" else "clean"), []).append(
                                float((~np.isnan(yhat))[ev[h]].mean())
                            )
                    for theta in cfg["warning"]["thresholds"]:
                        delta = thresholds[m][str(theta)][str(h)]
                        for c2, source in (("clean", clean_preds), (cond, preds)):
                            yhat = source[m][h]
                            fl = warning_flags(yhat[ev[h]], theta, delta)
                            pr, rc = hourly_scores(y_ev[h][ev[h]] > theta, fl)
                            f2acc.setdefault(
                                (m, h, c2 if c2 == "clean" else cond, theta), []
                            ).append((seed, pr, rc, fbeta(pr, rc, 2.0)))
    return _write(cfg, tables, guard, acc, f2acc, cover, det_rows, seeds, methods, horizons)


def _write(cfg, tables, guard, acc, f2acc, cover, det_rows, seeds, methods, horizons) -> dict:
    rows = []
    # clean rows are recomputed per fault condition (same rows); keep one clean entry per scope
    for (m, h, cond, scope), vals in sorted(acc.items()):
        by_seed: dict = {}
        for seed, r, n in vals:
            by_seed.setdefault(seed, (r, n))  # clean values repeat per condition: keep the first
        r = np.array([v[0] for v in by_seed.values()])
        rows.append({"method": m, "h": h, "condition": cond, "scope": scope,
                     "rmse_mean": float(r.mean()), "rmse_std": float(r.std(ddof=0)),
                     "n_mean": float(np.mean([v[1] for v in by_seed.values()])),
                     "seeds": len(r)})  # fmt: skip
    df = pd.DataFrame(rows)
    out = []
    for (m, h, scope), g in df.groupby(["method", "h", "scope"]):
        by = g.set_index("condition")
        if not {"edge_off", "edge_on", "clean"} <= set(by.index):
            continue
        off, on, cl = (by.loc[c, "rmse_mean"] for c in ("edge_off", "edge_on", "clean"))
        out.append({"method": m, "h": h, "scope": scope, "rmse_clean": cl, "rmse_edge_off": off,
                    "rmse_edge_on": on, "damage_off": off - cl, "damage_on": on - cl,
                    "recovered_pct": 100 * (off - on) / (off - cl) if off - cl > 1e-9 else np.nan,
                    "n": by.loc["edge_off", "n_mean"]})  # fmt: skip
    pd.DataFrame(out).to_csv(tables / "rq3b_robustness.csv", index=False)
    f2 = []
    for (m, h, cond, theta), vals in sorted(f2acc.items()):
        a = np.array([[v[1], v[2], v[3]] for v in {x[0]: x for x in vals}.values()])
        f2.append({"method": m, "h": h, "condition": cond, "theta": theta,
                   "precision": a[:, 0].mean(), "recall": a[:, 1].mean(), "f2": a[:, 2].mean(),
                   "f2_std": a[:, 2].std()})  # fmt: skip
    pd.DataFrame(f2).to_csv(tables / "rq3b_warning.csv", index=False)
    det = pd.DataFrame(det_rows)
    agg = det.groupby("type")[["hours", "hours_flagged", "segments", "segments_detected"]].sum()
    agg["hours_flagged_pct"] = 100 * agg["hours_flagged"] / agg["hours"].clip(lower=1)
    agg["segments_detected_pct"] = (
        100 * agg["segments_detected"] / agg["segments"].replace(0, np.nan)
    )
    agg.reset_index().to_csv(tables / "rq3b_detection.csv", index=False)
    summary = {
        "evaluated_on": "test inputs (targets untouched)",
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "seeds": seeds, "methods": methods, "horizons": horizons,
        "persistence_coverage": {k: float(np.mean(v)) for k, v in cover.items()},
        "note": "synthetic faults; measures forecast robustness, not fault-detection quality",
    }  # fmt: skip
    guard.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
