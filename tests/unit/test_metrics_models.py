import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.eval.metrics import (
    improvement_vs_persistence,
    mae,
    r2,
    rmse,
    smape,
    summarize,
)
from airq.eval.sanity import sanity_alarms
from airq.models.baselines import persistence, seasonal_naive
from airq.models.gbm import predict, save_model, train_lgbm
from airq.models.manifest import ManifestError, load_model_checked, record_model

CFG = load_config()


def test_metrics_on_hand_computed_example():
    y = [1.0, 2.0, 3.0, 4.0]
    yhat = [1.0, 3.0, 3.0, 2.0]
    assert np.isclose(rmse(y, yhat), np.sqrt((0 + 1 + 0 + 4) / 4))
    assert np.isclose(mae(y, yhat), (0 + 1 + 0 + 2) / 4)
    assert np.isclose(r2(y, yhat), 1 - 5 / 5)  # SS_tot = 5, SS_res = 5
    expected = 100 * np.mean([0, 2 * 1 / 5, 0, 2 * 2 / 6])
    assert np.isclose(smape(y, yhat, eps=0.0), expected)
    assert summarize(y, yhat)["n"] == 4


def test_improvement_vs_persistence():
    assert np.isclose(improvement_vs_persistence(20.0, 18.0), 10.0)
    assert improvement_vs_persistence(20.0, 22.0) < 0


def test_sanity_alarm_triggers_on_suspiciously_good_results():
    assert sanity_alarms({1: 20.0, 6: 52.0, 24: 81.0}, 0.5, CFG) == []
    alarms = sanity_alarms({1: 5.0, 6: 52.0, 24: 81.0}, 0.95, CFG)
    assert len(alarms) == 2 and "h=1" in alarms[0] and "R2" in alarms[1]


def _two_station_frame():
    ts = pd.date_range("2016-01-01", periods=60, freq="h")
    rows = []
    for st, off in (("A", 0.0), ("B", 100.0)):
        rows.append(pd.DataFrame({"station": st, "ts": ts, "pm25": np.arange(60.0) + off}))
    return pd.concat(rows, ignore_index=True)


def test_persistence_and_seasonal_naive_definitions():
    df = _two_station_frame()
    assert (persistence(df) == df["pm25"]).all()
    s = seasonal_naive(df, h=6)  # y_hat(t+6) = pm25(t+6-24) = pm25(t-18)
    a = df[df["station"] == "A"].index
    assert s.loc[a[30]] == df.loc[a[30 - 18], "pm25"]
    assert np.isnan(s.loc[a[10]])  # not enough history
    b0 = df[df["station"] == "B"].index[0]
    assert np.isnan(s.loc[b0])  # does not borrow from station A
    with pytest.raises(ValueError):
        seasonal_naive(df, h=25)


def _tiny_model(tmp_path):
    rng = np.random.default_rng(0)
    x = pd.DataFrame({"a": rng.normal(size=300), "b": rng.normal(size=300)})
    y = 3 * x["a"].to_numpy() + rng.normal(0, 0.1, 300)
    cfg = json.loads(json.dumps(CFG))
    cfg["forecast"]["lgbm"].update(
        n_estimators=50, early_stopping=10, num_leaves=7, min_child_samples=5
    )
    model = train_lgbm(x[:200], y[:200], x[200:], y[200:], ["a", "b"], cfg)
    save_model(model, tmp_path / "lgbm_h1_k0.txt")
    return model, x


def test_lgbm_trains_saves_as_text_and_reloads_identically(tmp_path):
    model, x = _tiny_model(tmp_path)
    record_model(tmp_path, "h1_k0", "lgbm_h1_k0.txt", ["a", "b"], "cfg123")
    loaded = load_model_checked(tmp_path, "h1_k0", ["a", "b"])
    assert isinstance(loaded, lgb.Booster)
    np.testing.assert_allclose(
        loaded.predict(x[["a", "b"]]), predict(model, x, ["a", "b"]), rtol=1e-6
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["models"]["h1_k0"]["features"] == ["a", "b"]
    assert manifest["lightgbm_version"] == lgb.__version__


def test_manifest_rejects_feature_list_mismatch(tmp_path):
    _tiny_model(tmp_path)
    record_model(tmp_path, "h1_k0", "lgbm_h1_k0.txt", ["a", "b"], "cfg123")
    with pytest.raises(ManifestError, match="mismatch"):
        load_model_checked(tmp_path, "h1_k0", ["b", "a"])  # order matters
    with pytest.raises(ManifestError, match="mismatch"):
        load_model_checked(tmp_path, "h1_k0", ["a", "b", "c"])
    with pytest.raises(ManifestError, match="not in manifest"):
        load_model_checked(tmp_path, "h6_k0", ["a", "b"])


def test_manifest_rejects_lightgbm_major_version_change(tmp_path):
    _tiny_model(tmp_path)
    record_model(tmp_path, "h1_k0", "lgbm_h1_k0.txt", ["a", "b"], "cfg123")
    path = tmp_path / "manifest.json"
    m = json.loads(path.read_text())
    m["lightgbm_version"] = "3.3.5"
    path.write_text(json.dumps(m))
    with pytest.raises(ManifestError, match="major version"):
        load_model_checked(tmp_path, "h1_k0", ["a", "b"])
