"""Generate paper/numbers.tex and paper/NUMBERS.md from reports/ (TALIMAT 11.4).

Every number the paper quotes in running text is a LaTeX macro defined in paper/numbers.tex; the macro
is read from ONE cell of a file under reports/tables (or from a documented derivation: a mean, a sum
or a count over a selected group). paper/NUMBERS.md maps each macro to its file, selector and column,
so a reviewer can check the paper against the results one line at a time. Nothing is typed by hand.

    python -m scripts.make_paper_numbers          # writes paper/numbers.tex and paper/NUMBERS.md
    python -m scripts.make_paper_numbers --check  # fails if the committed files are out of date
"""

from __future__ import annotations

# ruff: noqa: E501  (macro definitions and the generated-table descriptions are long on purpose)
import argparse
import contextlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "reports" / "tables"
OUT_TEX = ROOT / "paper" / "numbers.tex"
OUT_MD = ROOT / "paper" / "NUMBERS.md"

DIGITS = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five",
          "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine"}  # fmt: skip
H_NAME = {1: "HOne", 6: "HSix", 24: "HTwentyFour", "any": "HAny"}
LOSS_NAME = {0.05: "Five", 0.10: "Ten", 0.20: "Twenty"}
MODELS = {  # file label -> short macro part
    "B0_persistence": "Persist", "B1_seasonal_naive": "Seasonal", "B2_ridge_k0": "Ridge",
    "M1_lgbm_k0": "Mone", "M2_lgbm_k3": "Mtwoa", "M2_lgbm_k11": "Mtwob",
}  # fmt: skip

_cache: dict[str, pd.DataFrame] = {}
ROWS: list[dict] = []
_names: set[str] = set()


def table(name: str) -> pd.DataFrame:
    if name not in _cache:
        _cache[name] = pd.read_csv(TABLES / f"{name}.csv")
    return _cache[name]


def macro_name(*parts: str) -> str:
    text = "".join(p[:1].upper() + p[1:] for p in parts)
    for d, w in DIGITS.items():
        text = text.replace(d, w)
    return "n" + text


def _mask(df: pd.DataFrame, flt: dict) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for col, val in flt.items():
        if isinstance(val, float):
            m &= np.isclose(df[col].astype(float), val)
        else:
            m &= df[col].astype(str) == str(val)
    return m


def _sel(flt: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in flt.items()) or "(all rows)"


def put(name: str, value, fmt: str, file: str, sel: str, col: str, how: str) -> None:
    if name in _names:
        raise ValueError(f"duplicate macro {name}")
    _names.add(name)
    text = value if isinstance(value, str) else format(float(value), fmt)
    ROWS.append({"macro": name, "value": text, "file": file, "selector": sel, "column": col,
                 "how": how})  # fmt: skip


def cell(name: str, file: str, col: str, fmt: str = ".2f", scale: float = 1.0, **flt) -> None:
    df = table(file)
    sub = df[_mask(df, flt)]
    if len(sub) != 1:
        raise ValueError(f"{name}: {file} {flt} matched {len(sub)} rows, expected 1")
    v = sub.iloc[0][col]
    if isinstance(v, str) and fmt:  # mixed-type column (scenarios_summary.measured) arrives as text
        with contextlib.suppress(ValueError):
            v = float(v)
    if not isinstance(v, str):
        v = float(v) * scale
    put(name, v, fmt, f"reports/tables/{file}.csv", _sel(flt), col,
        "cell" if scale == 1.0 else f"cell x {scale:g}")  # fmt: skip


def agg(
    name: str, file: str, col: str, fn: str, fmt: str = ".1f", scale: float = 1.0, **flt
) -> None:
    df = table(file)
    sub = df[_mask(df, flt)]
    if sub.empty:
        raise ValueError(f"{name}: {file} {flt} matched no rows")
    fns = {"mean": lambda: sub[col].mean(), "sum": lambda: sub[col].sum(), "count": lambda: float(len(sub)),
           "std": lambda: sub[col].std(ddof=0)}  # fmt: skip
    v = fns[fn]() * scale
    put(
        name,
        v,
        fmt,
        f"reports/tables/{file}.csv",
        _sel(flt),
        col,
        f"derived: {fn} over the selected rows",
    )


def count_where(name: str, file: str, col: str, pred_desc: str, mask: pd.Series, **flt) -> None:
    df = table(file)
    sub = df[_mask(df, flt)]
    n = int(mask.loc[sub.index].sum()) if len(sub) else 0
    put(name, float(n), ".0f", f"reports/tables/{file}.csv", _sel(flt) + f", where {pred_desc}", col,
        "derived: count")  # fmt: skip


# --- the numbers -------------------------------------------------------------------------------------
def dataset(cfg: dict) -> None:
    f = "dataset_summary"
    cell("nDataRows", f, "rows", ".0f", station="ALL")
    cell("nDataHours", f, "rows", ".0f", station="Aotizhongxin")
    cell("nDataMissingPct", f, "pm25_missing_pct", ".2f", station="ALL")
    cell("nDataMean", f, "pm25_mean", ".1f", station="ALL")
    cell("nDataPNinetyFive", f, "pm25_p95", ".0f", station="ALL")
    # NOTE: physical_consistency.csv is computed on the TRAINING split only (257,751 pairs), where the
    # share is 8.2 %; over the whole dataset it is 5.2 %. The macro name says which one the paper quotes.
    cell(
        "nPmInconsistentTrainPct", "physical_consistency", "pct_pm25_gt_pm10", ".1f", station="ALL"
    )
    df = table(f)
    put("nDataStations", float((df.station != "ALL").sum()), ".0f", "reports/tables/dataset_summary.csv",
        "station != ALL", "station", "derived: count")  # fmt: skip
    for part in ("train", "val", "test"):
        for i, end in enumerate(("Start", "End")):
            v = cfg["split"][part][i][:7]
            put(macro_name(part, end), v, "", "configs/default.yaml", f"split.{part}[{i}]", "date",
                "config, first 7 characters (year-month)")  # fmt: skip
    agg(
        "nEventsHaze",
        "rq2_haze",
        "n_events",
        "mean",
        ".0f",
        grid="spec",
        method="B0_persistence",
        h="1",
    )
    cell(
        "nEventsFifty",
        "rq2_warning",
        "n_events",
        ".0f",
        grid="spec",
        method="B0_persistence",
        theta=75,
        h="1",
    )
    cell(
        "nEventsHundred",
        "rq2_warning",
        "n_events",
        ".0f",
        grid="spec",
        method="B0_persistence",
        theta=150,
        h="1",
    )


def rq1() -> None:
    for model, short in MODELS.items():
        for h in (1, 6, 24):
            cell(macro_name("rmse", short, H_NAME[h]), "rq1_main", "rmse", ".2f", model=model, h=h)
            cell(
                macro_name("impr", short, H_NAME[h]),
                "rq1_main",
                "improvement_vs_b0_pct",
                ".1f",
                model=model,
                h=h,
            )
    for h in (1, 6, 24):
        for col, key in (("pct_ci_lo", "CiLo"), ("pct_ci_hi", "CiHi")):
            cell(
                macro_name("impr", "Mtwob", key, H_NAME[h]),
                "rq1_main",
                col,
                ".1f",
                model="M2_lgbm_k11",
                h=h,
            )
        cell(
            macro_name("sig", "Mtwob", H_NAME[h]),
            "rq1_main",
            "stations_sig_vs_b0",
            "",
            model="M2_lgbm_k11",
            h=h,
        )
        for model, short in (("M2_lgbm_k3", "Kthree"), ("M2_lgbm_k11", "Keleven")):
            cell(
                macro_name("abl", short, H_NAME[h]),
                "rq1_ablation",
                "improvement_vs_m1_pct",
                ".1f",
                model=model,
                h=h,
            )
            cell(
                macro_name("abl", short, "Sig", H_NAME[h]),
                "rq1_ablation",
                "stations_sig_vs_m1",
                "",
                model=model,
                h=h,
            )
        agg(
            macro_name("loso", "Mean", H_NAME[h]),
            "rq1_loso",
            "improvement_loso_pct",
            "mean",
            ".1f",
            h=h,
        )
        agg(
            macro_name("loso", "InSample", H_NAME[h]),
            "rq1_loso",
            "improvement_in_sample_pct",
            "mean",
            ".1f",
            h=h,
        )
        df = table("rq1_loso")
        count_where(macro_name("loso", "Better", H_NAME[h]), "rq1_loso", "improvement_loso_pct",
                    "improvement_loso_pct > 0", df.improvement_loso_pct > 0, h=h)  # fmt: skip
        st = table("rq1_stats")
        count_where(macro_name("dm", "Mtwob", "VsB", "Zero", H_NAME[h]), "rq1_stats", "significant",
                    "significant is True", st.significant.astype(str) == "True",
                    comparison="M2_lgbm_k11 vs B0", h=h)  # fmt: skip
        count_where(macro_name("dm", "Mtwob", "VsM", "One", H_NAME[h]), "rq1_stats", "significant",
                    "significant is True", st.significant.astype(str) == "True",
                    comparison="M2_lgbm_k11 vs M1", h=h)  # fmt: skip
        cell(
            macro_name("shap", "Lag", "Zero", H_NAME[h]),
            "rq1_shap_top",
            "mean_abs_shap",
            ".1f",
            h=h,
            k=11,
            feature="pm25_lag0",
        )
        cell(
            macro_name("shap", "Nb", "Mean", H_NAME[h]),
            "rq1_shap_top",
            "mean_abs_shap",
            ".1f",
            h=h,
            k=11,
            feature="nb_mean",
        )
        for model, short in (("B0_persistence", "Persist"), ("M2_lgbm_k11", "Mtwob")):
            sub = {"subset": "target >= train p95", "model": model, "h": h}
            cell(macro_name("ext", "Rmse", short, H_NAME[h]), "rq1_extreme", "rmse", ".1f", **sub)
            cell(macro_name("ext", "Bias", short, H_NAME[h]), "rq1_extreme", "bias", ".0f", **sub)
    cell(
        "nExtPNinetyFive",
        "rq1_extreme",
        "p95",
        ".0f",
        subset="target >= train p95",
        model="B0_persistence",
        h=1,
    )
    agg("nLosoStations", "rq1_loso", "station", "count", ".0f", h=1)
    cell("nNowcastRmse", "rq1_nowcast", "rmse", ".1f", h=0)
    cell("nTuneGainTenTwenty", "rq1_tuning_convergence", "gain_10_to_20_pct", ".1f", study="MEAN")


def rq2() -> None:
    for method, short in (("B0_persistence", "Persist"), ("M2_lgbm_k11", "Mtwob")):
        for h in (1, 6, 24):
            sel = {"grid": "spec", "method": method, "theta": 150, "h": str(h)}
            for col, key, fmt in (("precision", "Prec", ".3f"), ("recall", "Rec", ".3f"), ("f2", "Ftwo", ".3f"),
                                  ("false_alarm_rate", "Fa", ".3f"), ("event_recall", "EvRec", ".3f"),
                                  ("m_event_recall", "MEvRec", ".2f"), ("lead_median", "Lead", ".0f"),
                                  ("m_lead_median", "MLead", ".0f"), ("delta", "Delta", ".0f")):  # fmt: skip
                cell(macro_name("warn", key, short, H_NAME[h]), "rq2_warning", col, fmt, **sel)
            hz = {"grid": "spec", "method": method, "h": str(h)}
            cell(
                macro_name("haze", "Caught", short, H_NAME[h]), "rq2_haze", "n_caught", ".0f", **hz
            )
        cell(macro_name("warn", "EvRec", short, "HAny"), "rq2_warning", "event_recall", ".3f",
             grid="spec", method=method, theta=150, h="any")  # fmt: skip


def rq3b() -> None:
    for method, short in (
        ("B0_persistence", "Persist"),
        ("M1_lgbm_k0", "Mone"),
        ("M2_lgbm_k11", "Mtwob"),
    ):
        for h in (1, 6, 24):
            sel = {"method": method, "h": h, "scope": "affected"}
            for col, key, fmt in (("rmse_clean", "Clean", ".2f"), ("damage_off", "Off", ".1f"),
                                  ("damage_on", "On", ".1f"), ("recovered_pct", "Rec", ".1f")):  # fmt: skip
                cell(macro_name("rob", key, short, H_NAME[h]), "rq3b_robustness", col, fmt, **sel)
    for scope, sname in (("spike", "Spike"), ("stuck", "Stuck"), ("dropout", "Dropout")):
        for method, short in (("B0_persistence", "Persist"), ("M2_lgbm_k11", "Mtwob")):
            sel = {"method": method, "h": 1, "scope": scope}
            cell(
                macro_name("rob", sname, "Off", short),
                "rq3b_robustness",
                "damage_off",
                ".1f",
                **sel,
            )
            cell(
                macro_name("rob", sname, "On", short), "rq3b_robustness", "damage_on", ".1f", **sel
            )


def rq3a() -> None:
    base = {"speedup": 3600.0, "offline_k": 0, "delay_ms": 0.0}
    for loss, name in LOSS_NAME.items():
        sel = {**base, "loss": loss}
        cell(macro_name("pdr", name), "rq3a_bench", "pdr_mean", ".3f", **sel)
        cell(macro_name("dmg", name), "rq3a_bench", "paired_delta_h1_mean", ".2f", **sel)
        cell(macro_name("dmg", name, "Std"), "rq3a_bench", "paired_delta_h1_std", ".2f", **sel)
        agg(
            macro_name("behind", name),
            "rq3a_bench",
            "behind_runs",
            "sum",
            ".0f",
            speedup=3600.0,
            offline_k=0,
            loss=loss,
        )  # both delay settings
        agg(
            macro_name("runs", name),
            "rq3a_bench",
            "reps",
            "sum",
            ".0f",
            speedup=3600.0,
            offline_k=0,
            loss=loss,
        )
    agg("nRunsTotal", "rq3a_bench", "reps", "sum", ".0f")
    cell("nLatDbMedian", "rq3a_bench", "lat_db_p50_ms_mean", ".0f", **{**base, "loss": 0.0})
    cell(
        "nLatDbMedianDelay",
        "rq3a_bench",
        "lat_db_p50_ms_mean",
        ".0f",
        speedup=3600.0,
        offline_k=0,
        delay_ms=200.0,
        loss=0.0,
    )
    cell(
        "nWarnLatKeepUp",
        "rq3a_bench",
        "lat_warn_p50_ms_median",
        ".1f",
        scale=1e-3,
        **{**base, "loss": 0.0},
    )
    cell(
        "nWarnLatBehind",
        "rq3a_bench",
        "lat_warn_p50_ms_median",
        ".0f",
        scale=1e-3,
        **{**base, "loss": 0.20},
    )
    cell("nRssPredictor", "rq3a_bench", "rss_mb_predictor_mean", ".0f", **{**base, "loss": 0.0})
    fast = {"speedup": 36000.0, "loss": 0.0, "delay_ms": 0.0}
    cell(
        "nOffLatFullBefore",
        "rq3a_bench",
        "lat_warn_p50_ms_median",
        ".1f",
        scale=1e-3,
        offline_k=0,
        **fast,
    )
    cell(
        "nOffLatOneBefore",
        "rq3a_bench",
        "lat_warn_p50_ms_median",
        ".1f",
        scale=1e-3,
        offline_k=1,
        **fast,
    )
    cell("nOffBehindOneBefore", "rq3a_bench", "behind_runs", ".0f", offline_k=1, **fast)
    for k, name in ((0, "Full"), (1, "One"), (3, "Three"), (6, "Six")):
        cell(macro_name("off", "Lat", name, "After"), "rq3a_bench_offline_fix", "lat_warn_p50_ms_median",
             ".1f", scale=1e-3, offline_k=k, **fast)  # fmt: skip
        cell(macro_name("off", "Behind", name, "After"), "rq3a_bench_offline_fix", "behind_runs", ".0f",
             offline_k=k, **fast)  # fmt: skip
    for k, name in ((1, "One"), (3, "Three"), (6, "Six")):
        cell(
            macro_name("off", "Nb", name),
            "rq3a_bench_offline_fix",
            "n_neighbors_mean_mean",
            ".1f",
            offline_k=k,
            **fast,
        )


def rq4() -> None:
    for h in (1, 6, 24):
        for variant, vname in (("raw", "Raw"), ("calibrated", "Cal")):
            sel = {"h": h, "variant": variant, "subset": "all"}
            cell(macro_name("cov", vname, H_NAME[h]), "rq4_coverage", "coverage", ".3f", **sel)
            cell(macro_name("cov", "Ext", vname, H_NAME[h]), "rq4_coverage", "coverage", ".3f",
                 h=h, variant=variant, subset="target >= train p95")  # fmt: skip
        cell(
            macro_name("width", "Cal", H_NAME[h]),
            "rq4_coverage",
            "mean_width",
            ".1f",
            h=h,
            variant="calibrated",
            subset="all",
        )
        cell(
            macro_name("factor", H_NAME[h]),
            "rq4_coverage",
            "c",
            ".2f",
            h=h,
            variant="calibrated",
            subset="all",
        )
        for method, short in (("M2_lgbm_k11", "Mtwob"), ("M3_q90_cal", "Qnine")):
            sel = {"grid": "spec", "method": method, "theta": 150, "h": h}
            for col, key, fmt in (("precision", "Prec", ".3f"), ("recall", "Rec", ".3f"), ("f2", "Ftwo", ".3f"),
                                  ("false_alarm_rate", "Fa", ".3f")):  # fmt: skip
                cell(macro_name("qw", key, short, H_NAME[h]), "rq4_warning", col, fmt, **sel)


def scenarios() -> None:
    s = table("scenarios_summary")
    put(
        "nScnTotal",
        float(len(s)),
        ".0f",
        "reports/tables/scenarios_summary.csv",
        "(all rows)",
        "verdict",
        "derived: count",
    )
    count_where(
        "nScnConfirmed",
        "scenarios_summary",
        "verdict",
        "verdict == confirmed",
        s.verdict == "confirmed",
    )
    count_where(
        "nScnRefuted", "scenarios_summary", "verdict", "verdict == refuted", s.verdict == "refuted"
    )
    cell(
        "nScnStuckMeasured",
        "scenarios_summary",
        "measured",
        ".1f",
        scenario="sensor_takilmasi",
        metric="mae_next_6h_h6",
    )
    cell(
        "nScnStuckReference",
        "scenarios_summary",
        "reference",
        ".1f",
        scenario="sensor_takilmasi",
        metric="mae_next_6h_h6",
    )
    cell(
        "nScnDelivery",
        "scenarios_summary",
        "measured",
        ".2f",
        scenario="ag_bozulmasi",
        metric="delivery_ratio",
    )
    cell(
        "nScnLatencyP",
        "scenarios_summary",
        "measured",
        ".0f",
        scenario="ag_bozulmasi",
        metric="latency_p95_ms",
    )
    cell(
        "nScnHazeLead",
        "scenarios_summary",
        "measured",
        ".0f",
        scenario="gercek_haze_replay",
        metric="lead_time_h",
    )
    ab = table("scenarios_ab")
    for fault, fname in (("sensor_sicramasi", "Spike"), ("sensor_takilmasi", "Stuck")):
        for edge, ename in (("off", "Off"), ("on", "On")):
            for col, hname in (("mae_window_h1", "HOne"), ("mae_window_h6", "HSix")):
                agg(
                    macro_name("ab", fname, ename, hname),
                    "scenarios_ab",
                    col,
                    "mean",
                    ".1f",
                    fault=fault,
                    edge=edge,
                )
        for col, hname in (("mae_window_h1", "HOne"), ("mae_window_h6", "HSix")):
            off = ab[(ab.fault == fault) & (ab.edge == "off")][col].mean()
            on = ab[(ab.fault == fault) & (ab.edge == "on")][col].mean()
            put(macro_name("ab", fname, "Gain", hname), off - on, ".1f", "reports/tables/scenarios_ab.csv",
                f"fault={fault}", col, "derived: mean(edge off) - mean(edge on)")  # fmt: skip
        merged = ab[ab.fault == fault].pivot(index="start", columns="edge", values="mae_window_h1")
        put(macro_name("ab", fname, "Wins"), float((merged["off"] > merged["on"]).sum()), ".0f",
            "reports/tables/scenarios_ab.csv", f"fault={fault}", "mae_window_h1",
            "derived: start dates where edge-off error > edge-on error")  # fmt: skip
        put(macro_name("ab", fname, "Windows"), float(len(merged)), ".0f", "reports/tables/scenarios_ab.csv",
            f"fault={fault}", "start", "derived: number of start dates")  # fmt: skip


def config_and_env(cfg: dict) -> None:
    """Design constants and the machine description: read from configs/default.yaml / reports/bench/env.json."""
    items = [
        ("nSeed", cfg["project"]["seed"], "project.seed"),
        ("nOptunaTrials", cfg["forecast"]["optuna_trials"], "forecast.optuna_trials"),
        (
            "nExtremeQuantilePct",
            round(cfg["forecast"]["extreme_quantile"] * 100),
            "forecast.extreme_quantile x 100",
        ),
        ("nWaitMs", cfg["iot"]["predictor_wait_ms"], "iot.predictor_wait_ms"),
        ("nCooldownH", cfg["warning"]["cooldown_h"], "warning.cooldown_h"),
        ("nBeta", cfg["warning"]["beta"], "warning.beta"),
        ("nThetaLow", cfg["warning"]["thresholds"][0], "warning.thresholds[0]"),
        ("nThetaHigh", cfg["warning"]["thresholds"][1], "warning.thresholds[1]"),
        ("nSpeedSlow", cfg["bench"]["speedup"][0], "bench.speedup[0]"),
        ("nSpeedFast", cfg["bench"]["speedup"][1], "bench.speedup[1]"),
        ("nReps", cfg["bench"]["repeats"], "bench.repeats"),
        ("nFfillLimit", cfg["data"]["ffill_limit"], "data.ffill_limit"),
        ("nHazeMinStations", cfg["episodes"]["haze"]["min_stations"], "episodes.haze.min_stations"),
        ("nHazeMinHours", cfg["episodes"]["haze"]["min_hours"], "episodes.haze.min_hours"),
        (
            "nEventMinHours",
            cfg["episodes"]["exceedance"]["min_hours"],
            "episodes.exceedance.min_hours",
        ),
        (
            "nEventMergeGapH",
            cfg["episodes"]["exceedance"]["merge_gap_h"],
            "episodes.exceedance.merge_gap_h",
        ),
        ("nWarnWindowH", cfg["warning"]["window_h"], "warning.window_h"),
        ("nQuantLow", cfg["forecast"]["quantiles"][0], "forecast.quantiles[0]"),
        ("nQuantMid", cfg["forecast"]["quantiles"][1], "forecast.quantiles[1]"),
        ("nQuantHigh", cfg["forecast"]["quantiles"][2], "forecast.quantiles[2]"),
        ("nKThree", cfg["forecast"]["neighbor_k"][1], "forecast.neighbor_k[1]"),
        ("nKEleven", cfg["forecast"]["neighbor_k"][2], "forecast.neighbor_k[2]"),
        ("nSimDays", cfg["bench"]["sim_days"], "bench.sim_days"),
    ]
    for name, value, key in items:
        fmt = (
            ".0f" if float(value).is_integer() else ".1f"
        )  # quantiles 0.1 / 0.5 / 0.9 keep their decimal
        put(name, float(value), fmt, "configs/default.yaml", key, "value", "config")
    env = json.loads((ROOT / "reports" / "bench" / "env.json").read_text(encoding="utf-8"))
    unc = json.loads(
        (ROOT / "reports" / "metrics" / "uncertainty_test.json").read_text(encoding="utf-8")
    )
    put(
        "nTargetCoverage",
        float(unc["target_coverage"]),
        ".2f",
        "reports/metrics/uncertainty_test.json",
        "target_coverage",
        "target_coverage",
        "cell",
    )
    put(
        "nCpuCount",
        float(env["cpu_count"]),
        ".0f",
        "reports/bench/env.json",
        "cpu_count",
        "cpu_count",
        "cell",
    )
    put(
        "nRamGb",
        float(env["ram_gb"]),
        ".0f",
        "reports/bench/env.json",
        "ram_gb",
        "ram_gb",
        "cell, rounded",
    )
    put("nPyVersion", env["python"], "", "reports/bench/env.json", "python", "python", "cell")
    broker = env["broker"].replace("mosquitto version ", "")
    put(
        "nBrokerVersion",
        broker,
        "",
        "reports/bench/env.json",
        "broker",
        "broker",
        "cell, 'mosquitto version' removed",
    )


FIGURES = ["architecture", "eda_corr_missing", "rq1_horizon", "rq1_ablation_loso", "rq1_shap_groups",
           "rq2_haze_example", "rq2_pr_lead", "rq3a_system", "rq3b_damage", "rq4_uncertainty",
           "scenarios_edge", "scenarios_ab"]  # fmt: skip


def copy_figures() -> int:
    """paper/ is self-contained (Overleaf): copy the vector figures the paper uses next to main.tex."""
    dest = ROOT / "paper" / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in FIGURES:
        src = ROOT / "reports" / "figures" / f"{name}.pdf"
        data = src.read_bytes()
        target = dest / f"{name}.pdf"
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
        n += 1
    return n


def build() -> None:
    ROWS.clear()
    _names.clear()
    _cache.clear()
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text(encoding="utf-8"))
    config_and_env(cfg)
    dataset(cfg)
    rq1()
    rq2()
    rq3b()
    rq3a()
    rq4()
    scenarios()


def render() -> tuple[str, str]:
    tex = ["% Generated by scripts/make_paper_numbers.py from reports/tables: DO NOT EDIT BY HAND.",
           "% Each macro is one cell (or one documented derivation) of a results file; see NUMBERS.md."]  # fmt: skip
    for r in ROWS:
        tex.append(f"\\newcommand{{\\{r['macro']}}}{{{r['value']}}}")
    md = ["# NUMBERS: where every number in the paper comes from", "",
          "Generated by `python -m scripts.make_paper_numbers` (do not edit). A macro such as `\\nRmseMtwobHOne` "
          "is defined in `paper/numbers.tex` and used in `paper/main.tex`; the table below gives the file, "
          "the row selector and the column it is read from. *cell* = one value copied from the file; "
          "*derived* = a mean, sum or count over the selected rows (stated in the last column).", "",
          f"{len(ROWS)} macros.", "",
          "| Macro | Value | Source file | Selector | Column | How |", "|---|---|---|---|---|---|"]  # fmt: skip
    for r in ROWS:
        sel = r["selector"].replace("|", "/")
        md.append(
            f"| `\\{r['macro']}` | {r['value']} | `{r['file']}` | {sel} | `{r['column']}` | {r['how']} |"
        )
    return "\n".join(tex) + "\n", "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check", action="store_true", help="fail if the committed files are out of date"
    )
    args = ap.parse_args()
    build()
    tex, md = render()
    if args.check:
        ok = OUT_TEX.exists() and OUT_MD.exists()
        ok = (
            ok
            and OUT_TEX.read_text(encoding="utf-8") == tex
            and OUT_MD.read_text(encoding="utf-8") == md
        )
        print(
            "paper numbers are up to date"
            if ok
            else "paper numbers are OUT OF DATE: rerun make_paper_numbers"
        )
        return 0 if ok else 1
    OUT_TEX.parent.mkdir(parents=True, exist_ok=True)
    OUT_TEX.write_text(tex, encoding="utf-8", newline="\n")
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    nfig = copy_figures()
    print(
        f"wrote {OUT_TEX.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)} ({len(ROWS)} macros), {nfig} figures"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
