"""Day 18 check of NUMBERS.md: the paper's numbers must hold up against *independent* routes.

make_paper_numbers copies cells from reports/tables/*.csv. This file re-derives the same quantities another
way: arithmetic identities between macros, the separate metrics JSON files that the evaluation scripts
write, and (when the raw data is present) a fresh computation from the Beijing CSV files.
"""

# ruff: noqa: E501  (the assertions quote the paper's claims in full)
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import check_paper  # noqa: E402

HNAME = {1: "HOne", 6: "HSix", 24: "HTwentyFour"}


@pytest.fixture(scope="module")
def n():
    """Macro values as floats where possible (numbers.tex is the committed file the paper uses)."""
    out = {}
    for name, val in check_paper.load_macros().items():
        try:
            out[name] = float(val)
        except ValueError:
            out[name] = val
    return out


def metrics(name):
    return json.loads((ROOT / "reports" / "metrics" / f"{name}.json").read_text(encoding="utf-8"))


# --- identities between macros ----------------------------------------------------------------------
@pytest.mark.parametrize("h", [1, 6, 24])
@pytest.mark.parametrize("short", ["Ridge", "Mone", "Mtwoa", "Mtwob"])
def test_the_improvement_percent_follows_from_the_rmse_values(n, h, short):
    b0, m = n[f"nRmsePersist{HNAME[h]}"], n[f"nRmse{short}{HNAME[h]}"]
    assert 100 * (b0 - m) / b0 == pytest.approx(n[f"nImpr{short}{HNAME[h]}"], abs=0.1)


@pytest.mark.parametrize("who", ["Persist", "Mtwob"])
@pytest.mark.parametrize("h", [1, 6, 24])
def test_f2_follows_from_precision_and_recall(n, who, h):
    p, r = n[f"nWarnPrec{who}{HNAME[h]}"], n[f"nWarnRec{who}{HNAME[h]}"]
    assert 5 * p * r / (4 * p + r) == pytest.approx(n[f"nWarnFtwo{who}{HNAME[h]}"], abs=0.002)


@pytest.mark.parametrize("who", ["Mtwob", "Qnine"])
@pytest.mark.parametrize("h", [1, 6, 24])
def test_q90_warning_f2_follows_from_precision_and_recall(n, who, h):
    p, r = n[f"nQwPrec{who}{HNAME[h]}"], n[f"nQwRec{who}{HNAME[h]}"]
    assert 5 * p * r / (4 * p + r) == pytest.approx(n[f"nQwFtwo{who}{HNAME[h]}"], abs=0.002)


def test_the_message_loss_matches_the_delivery_ratio(n):
    for loss, name in ((0.05, "Five"), (0.10, "Ten"), (0.20, "Twenty")):
        assert n[f"nPdr{name}"] == pytest.approx(1 - loss, abs=0.01)


def test_the_run_counts_are_consistent(n):
    assert n["nRunsTotal"] == 57  # the specified grid
    assert n["nRunsFive"] == n["nRunsTen"] == n["nRunsTwenty"] == 6  # 2 delays x 3 repetitions
    assert n["nBehindTwenty"] <= n["nRunsTwenty"] and n["nBehindFive"] <= n["nRunsFive"]


def test_the_paper_may_say_every_horizon_for_the_unseen_station_claim(n):
    # "the model beats persistence at all stations at every horizon" (RQ1, LOSO): all three counts
    for h in ("HOne", "HSix", "HTwentyFour"):
        assert n[f"nLosoBetter{h}"] == n["nLosoStations"]


def test_the_scenario_verdicts_add_up(n):
    assert n["nScnConfirmed"] + n["nScnRefuted"] == n["nScnTotal"]


def test_the_paired_gain_is_the_difference_of_the_means(n):
    for fault in ("Spike", "Stuck"):
        for h in ("HOne", "HSix"):
            assert n[f"nAb{fault}Off{h}"] - n[f"nAb{fault}On{h}"] == pytest.approx(
                n[f"nAb{fault}Gain{h}"], abs=0.11
            )


def test_the_offline_fix_does_not_change_the_full_network(n):
    # the full-network latency before and after the fix is the same thing measured twice (noise only)
    assert n["nOffLatFullAfter"] == pytest.approx(n["nOffLatFullBefore"], rel=0.1)
    assert n["nOffLatOneAfter"] < 0.5 * n["nOffLatOneBefore"]  # the fix: one offline device
    assert n["nOffBehindOneAfter"] == 0


# --- independent files written by the evaluation scripts ----------------------------------------------
def test_the_event_counts_match_the_warning_metrics_file(n):
    w = metrics("warning_test")
    assert n["nEventsFifty"] == w["n_test_exceedance_events"]["75"]
    assert n["nEventsHundred"] == w["n_test_exceedance_events"]["150"]
    assert n["nEventsHaze"] == w["n_test_regional_haze"]


def test_the_best_test_rmse_is_the_best_of_the_rows_in_the_paper(n):
    best = metrics("forecast_test")["by_horizon_best"]
    for h in (1, 6, 24):
        ours = min(n[f"nRmse{m}{HNAME[h]}"] for m in ("Persist", "Ridge", "Mone", "Mtwoa", "Mtwob"))
        assert best[str(h)]["best_rmse"] == pytest.approx(ours, abs=0.006)


def test_the_extreme_threshold_and_interval_factors_match_the_metrics_files(n):
    f = metrics("forecast_test")
    assert n["nExtPNinetyFive"] == pytest.approx(f["train_p95"], abs=0.5)
    scales = metrics("uncertainty_test")["scales"]
    for h in (1, 6, 24):
        assert n[f"nFactor{HNAME[h]}"] == pytest.approx(scales[str(h)], abs=0.006)


def test_the_extreme_rmse_follows_from_the_stored_predictions_if_present(n):
    # the by-station table the paper does not use is an independent aggregate of the same predictions
    f = ROOT / "reports" / "tables" / "rq1_by_station.csv"
    if not f.exists():
        pytest.skip("no per-station table")
    df = pd.read_csv(f)
    assert {"h", "model"} <= set(df.columns)
    sub = df[(df.model == "M2_lgbm_k11") & (df.h == 1)]
    if "rmse" in sub.columns and "n" in sub.columns:
        pooled = np.sqrt((sub["rmse"] ** 2 * sub["n"]).sum() / sub["n"].sum())
        assert pooled == pytest.approx(n["nRmseMtwobHOne"], abs=0.02)


# --- recomputation from the raw dataset (only where the raw files exist) -----------------------------
def _raw_files():
    return sorted((ROOT / "data" / "raw" / "beijing").rglob("PRSA_Data_*.csv"))


@pytest.mark.skipif(not _raw_files(), reason="the raw Beijing CSV files are not on this machine")
def test_the_dataset_numbers_are_recomputed_from_the_raw_files(n):
    frames = [pd.read_csv(f, usecols=["PM2.5"]) for f in _raw_files()]
    assert len(frames) == int(n["nDataStations"])
    pm = pd.concat(frames, ignore_index=True)["PM2.5"]
    assert len(pm) == n["nDataRows"]
    assert len(frames[0]) == n["nDataHours"]
    assert 100 * pm.isna().mean() == pytest.approx(n["nDataMissingPct"], abs=0.005)
    assert pm.mean() == pytest.approx(n["nDataMean"], abs=0.05)
    assert pm.quantile(0.95) == pytest.approx(n["nDataPNinetyFive"], abs=0.5)


@pytest.mark.skipif(not _raw_files(), reason="the raw Beijing CSV files are not on this machine")
def test_the_pm_inconsistency_share_is_recomputed_from_the_raw_files(n):
    """8.2 % is the share in the TRAINING split (where the edge tolerance is chosen), not in all data.

    The day-18 check found the paper had called it "real data" (over all rows it is 5.2 %)."""
    cols = ["year", "month", "day", "hour", "PM2.5", "PM10"]
    raw = pd.concat([pd.read_csv(f, usecols=cols) for f in _raw_files()])
    raw["ts"] = pd.to_datetime(raw[["year", "month", "day", "hour"]])
    both = raw.dropna(subset=["PM2.5", "PM10"])
    share = lambda d: 100 * (d["PM2.5"] > d["PM10"]).mean()  # noqa: E731
    train = both[both["ts"] <= "2015-08-31 23:00"]
    assert share(train) == pytest.approx(n["nPmInconsistentTrainPct"], abs=0.05)
    assert (
        share(both) < n["nPmInconsistentTrainPct"] - 2
    )  # the whole-data share is lower: say "training"


# --- the text must not contradict the numbers it quotes ---------------------------------------------
def test_the_ordering_claims_in_the_text_hold(n):
    # "neighbours help at 1 h and 6 h, not at 24 h" (Discussion)
    assert n["nAblKelevenHOne"] > 2 and n["nAblKelevenHSix"] > 2 and n["nAblKelevenHTwentyFour"] < 1
    # "persistence beats LightGBM warning at 24 h" (RQ2)
    assert n["nWarnFtwoPersistHTwentyFour"] > n["nWarnFtwoMtwobHTwentyFour"]
    assert n["nWarnEvRecPersistHTwentyFour"] > n["nWarnEvRecMtwobHTwentyFour"]
    # "the q90 warning trades precision for recall at 24 h" (RQ4)
    assert n["nQwRecQnineHTwentyFour"] > n["nQwRecMtwobHTwentyFour"]
    assert n["nQwFaQnineHTwentyFour"] > n["nQwFaMtwobHTwentyFour"]
    # "models under-predict extremes and fall behind persistence" (RQ1)
    assert n["nExtRmseMtwobHTwentyFour"] > n["nExtRmsePersistHTwentyFour"]
    assert n["nExtBiasMtwobHTwentyFour"] > 0
    # "the filter helps the naive model more than LightGBM" (RQ3b)
    assert n["nRobRecPersistHOne"] > n["nRobRecMtwobHOne"]


def test_every_macro_used_in_the_text_exists():
    body = re.sub(
        r"(?<!\\)%.*$", "", (ROOT / "paper" / "main.tex").read_text(encoding="utf-8"), flags=re.M
    )
    used = set(re.findall(r"\\(n[A-Z][A-Za-z]*)\b", body))
    assert used <= set(check_paper.load_macros())
