"""Leakage and spec tests for features/build.py (TALIMAT section 10, tests 1-2)."""

import numpy as np
import pandas as pd
import pytest

from airq.data.clean import WIND_DEG, clean
from airq.features.build import FeatureConfig, build_features, make_target
from airq.features.neighbors import select_neighbors

N_HOURS = 400
START = "2016-03-01 00:00"
END = str(pd.Timestamp(START) + pd.Timedelta(hours=N_HOURS - 1))
STATIONS = ["S1", "S2", "S3", "S4"]
VALUE_COLS = ["pm25", "pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]


def make_df(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    ts = pd.date_range(START, periods=N_HOURS, freq="h")
    base = np.cumsum(rng.normal(0, 5, N_HOURS)) + 100
    for i, s in enumerate(STATIONS):
        d = pd.DataFrame({"station": s, "ts": ts})
        d["pm25"] = np.abs(base + rng.normal(0, 8, N_HOURS) + i * 3)
        for c in VALUE_COLS[1:]:
            d[c] = rng.normal(50, 10, N_HOURS)
        d["wd"] = rng.choice(list(WIND_DEG), N_HOURS)
        for c in VALUE_COLS:  # sprinkle gaps
            d.loc[rng.random(N_HOURS) < 0.04, c] = np.nan
        frames.append(d)
    return clean(pd.concat(frames, ignore_index=True), START, END, ffill_limit=3)


def scramble_future(df: pd.DataFrame, t: pd.Timestamp, seed: int = 1) -> pd.DataFrame:
    """Replace EVERY input value after t (all stations, all columns) with random junk."""
    rng = np.random.default_rng(seed)
    out = df.copy()
    fut = out["ts"] > t
    for c in out.columns:
        if c in ("station", "ts", "split"):
            continue
        if out[c].dtype == bool:
            out.loc[fut, c] = rng.random(fut.sum()) < 0.5
        else:
            out.loc[fut, c] = rng.normal(0, 1000, fut.sum())
    return out


CONFIGS = {
    "single": FeatureConfig(neighbor_k=0),
    "k2": FeatureConfig(
        neighbor_k=2,
        neighbors={"S1": ["S2", "S3"], "S2": ["S1", "S4"], "S3": ["S4", "S1"], "S4": ["S3", "S2"]},
    ),
    "all": FeatureConfig(neighbor_k=3),
}


@pytest.mark.parametrize("cfg_name", CONFIGS)
@pytest.mark.parametrize("t_idx", [60, 200, 333])
def test_no_future_information_in_any_feature_group(cfg_name, t_idx):
    cfg = CONFIGS[cfg_name]
    df = make_df()
    t = df["ts"].drop_duplicates().sort_values().iloc[t_idx]
    f1, meta = build_features(df, cfg)
    f2, _ = build_features(scramble_future(df, t), cfg)
    past1 = f1[f1["ts"] <= t].reset_index(drop=True)
    past2 = f2[f2["ts"] <= t].reset_index(drop=True)
    for group, cols in meta.groups.items():
        for c in cols:
            a, b = past1[c], past2[c]
            if c == "station":
                assert (a.astype(str) == b.astype(str)).all()
            else:
                assert np.array_equal(a.to_numpy(), b.to_numpy(), equal_nan=True), (
                    f"future leaked into {c} (group {group}, config {cfg_name})"
                )


def test_scramble_would_be_detected_if_a_feature_looked_ahead():
    """Guard against a vacuous test: features DO change when the past/present changes."""
    df = make_df()
    t = df["ts"].drop_duplicates().sort_values().iloc[200]
    f1, _ = build_features(df, CONFIGS["all"])
    df2 = df.copy()
    df2.loc[(df2["station"] == "S2") & (df2["ts"] == t), "pm25"] += 500
    f2, _ = build_features(df2, CONFIGS["all"])
    r1 = f1[(f1["station"] == "S1") & (f1["ts"] == t)].iloc[0]
    r2 = f2[(f2["station"] == "S1") & (f2["ts"] == t)].iloc[0]
    assert r1["nb_mean"] != r2["nb_mean"]  # neighbor's value at t is a legitimate input
    s2a = f1[(f1["station"] == "S2") & (f1["ts"] == t)].iloc[0]
    s2b = f2[(f2["station"] == "S2") & (f2["ts"] == t)].iloc[0]
    assert s2a["pm25_lag0"] != s2b["pm25_lag0"]


def test_lags_and_rolling_match_the_definition():
    df = make_df()
    feats, _ = build_features(df, CONFIGS["single"])
    g = df[df["station"] == "S1"].reset_index(drop=True)
    f = feats[feats["station"] == "S1"].reset_index(drop=True)
    i = 150
    assert f.loc[i, "pm25_lag0"] == np.float32(g.loc[i, "pm25"])
    assert f.loc[i, "pm25_lag24"] == np.float32(g.loc[i - 24, "pm25"])
    window = g.loc[i - 2 : i, "pm25"]  # window of 3 ends at t and includes t
    assert np.isclose(f.loc[i, "pm25_roll3_mean"], window.mean(), rtol=1e-5)
    assert np.isclose(f.loc[i, "pm25_roll3_max"], window.max(), rtol=1e-5)
    assert np.isclose(f.loc[i, "pm25_delta24"], g.loc[i, "pm25"] - g.loc[i - 24, "pm25"], rtol=1e-4)


def test_neighbor_mean_uses_only_other_stations_at_t():
    df = make_df()
    feats, meta = build_features(df, CONFIGS["all"])
    t = df["ts"].iloc[200]
    others = df[(df["station"] != "S1") & (df["ts"] == t)]["pm25"]
    row = feats[(feats["station"] == "S1") & (feats["ts"] == t)].iloc[0]
    assert np.isclose(row["nb_mean"], others.mean(), rtol=1e-5)
    assert row["n_neighbors_available"] == others.notna().sum()
    assert "n_neighbors_available" in meta.groups["neighbors"]


def test_neighbor_availability_drops_when_neighbors_are_missing():
    df = make_df()
    t = df["ts"].iloc[200]
    df.loc[
        (df["station"].isin(["S2", "S3"]))
        & (df["ts"] <= t)
        & (df["ts"] > t - pd.Timedelta(hours=10)),
        "pm25",
    ] = np.nan
    feats, _ = build_features(df, CONFIGS["all"])
    row = feats[(feats["station"] == "S1") & (feats["ts"] == t)].iloc[0]
    assert row["n_neighbors_available"] == 1  # only S4 remains


def test_target_is_future_observed_pm25_and_not_a_feature():
    df = make_df()
    feats, meta = build_features(df, CONFIGS["single"])
    assert not any("raw" in c for c in meta.feature_names)
    y = make_target(df, 6)
    s1 = df[df["station"] == "S1"].reset_index(drop=True)
    assert y.iloc[10] == s1.loc[16, "pm25_raw"] or (
        np.isnan(y.iloc[10]) and np.isnan(s1.loc[16, "pm25_raw"])
    )


def test_incomplete_calendar_is_rejected():
    df = make_df()
    df = df.drop(df.index[5])
    with pytest.raises(ValueError, match="complete hourly calendar"):
        build_features(df, CONFIGS["single"])


def test_k_smaller_than_network_requires_explicit_neighbors():
    with pytest.raises(ValueError, match="explicit"):
        build_features(make_df(), FeatureConfig(neighbor_k=2))


def test_neighbor_selection_is_fit_on_train_only():
    df = make_df()
    end = df["ts"].iloc[250]
    a = select_neighbors(df, 2, end)
    junk = df.copy()
    late = junk["ts"] > end
    junk.loc[late, "pm25_raw"] = np.random.default_rng(3).normal(0, 100, late.sum())
    assert select_neighbors(junk, 2, end) == a
    assert all(s not in v for s, v in a.items()) and all(len(v) == 2 for v in a.values())
