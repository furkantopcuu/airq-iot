"""Online (MQTT) features and predictions must equal the offline ones (TALIMAT section 10, test 5).

Same recorded data goes (a) through `clean()` + `build_features()` offline and (b) through
virtual devices -> MQTT -> edge gateway -> live predictor. If this fails the system is rejected.
"""

import copy
import threading
import time

import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.data.clean import clean
from airq.data.fixture import make_fixture_raw
from airq.data.load import load_raw
from airq.data.splits import horizon_mask
from airq.devices.fleet import run_fleet
from airq.edge.gateway import run as run_gateway
from airq.edge.quality import QualityParams
from airq.features.build import FeatureConfig, build_features, make_target
from airq.models.gbm import predict, save_model, train_lgbm
from airq.models.manifest import record_model
from airq.server import db
from airq.server.predictor import OnlinePredictor
from airq.server.predictor import run as run_predictor

pytestmark = pytest.mark.broker

CFG = copy.deepcopy(load_config())
CFG["forecast"]["lgbm"].update(
    n_estimators=25, early_stopping=5, num_leaves=15, min_child_samples=20
)
STATIONS = ["Dongsi", "Huairou"]
START, END = "2016-03-01 00:00", "2016-03-14 23:00"  # 14 simulated days
FIRST_PRED = pd.Timestamp("2016-03-10 23:00")  # 240 h of history are needed (168 + 72)


@pytest.fixture(scope="module")
def offline(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("parity")
    csv_dir = make_fixture_raw(tmp / "raw")
    raw = load_raw(csv_dir)
    raw = raw[raw["station"].isin(STATIONS)]
    cleaned = clean(raw, "2013-03-01", "2017-02-28 23:00", CFG["data"]["ffill_limit"])
    models_dir = tmp / "models"
    out = {"raw": raw, "models_dir": models_dir, "feats": {}}
    for k in (0, 1):
        feats, meta = build_features(cleaned, FeatureConfig.from_cfg(CFG, k=k))
        out["feats"][k] = (feats, meta)
        for h in CFG["forecast"]["horizons"]:
            y = make_target(cleaned, h).to_numpy()
            ok = ~np.isnan(y)
            tr = horizon_mask(cleaned["ts"], "train", h, CFG).to_numpy() & ok
            va = horizon_mask(cleaned["ts"], "val", h, CFG).to_numpy() & ok
            model = train_lgbm(feats[tr], y[tr], feats[va], y[va], meta.feature_names, CFG)
            save_model(model, models_dir / f"lgbm_h{h}_k{k}.txt")
            record_model(models_dir, f"h{h}_k{k}", f"lgbm_h{h}_k{k}.txt", meta.feature_names, "t")
    return out


def _wait(cond, timeout=120.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


@pytest.mark.parametrize("k", [0, 1])
def test_online_features_and_predictions_equal_offline(broker, offline, tmp_path, k):
    models_dir = offline["models_dir"]
    pred = OnlinePredictor(CFG, models_dir, k, STATIONS, wait_s=60.0, keep_log=True)
    stop = threading.Event()
    db_path = tmp_path / "parity.db"
    gw = threading.Thread(
        target=run_gateway,
        args=(QualityParams(), *broker, False, stop),  # edge filter OFF: flags only, values pass
        kwargs={"stats_every_s": 5},
    )
    pr = threading.Thread(
        target=run_predictor,
        args=(CFG, models_dir, db_path, *broker, k, STATIONS, None, stop),
        kwargs={"pred": pred},
    )
    gw.start()
    pr.start()
    time.sleep(1.5)  # both subscribed
    run_fleet(offline["raw"], STATIONS, START, END, *broker, speedup=0)
    n_ts = int((pd.Timestamp(END) - FIRST_PRED) / pd.Timedelta(hours=1)) + 1
    ok = _wait(lambda: len(pred.log) >= n_ts * len(STATIONS))
    stop.set()
    gw.join(timeout=15)
    pr.join(timeout=15)
    assert ok, f"predictor produced {len(pred.log)} of {n_ts * len(STATIONS)} expected rows"
    assert pred.expired == 0 and pred.late_dropped == 0  # nothing waited out, nothing re-predicted

    feats_off, meta = offline["feats"][k]
    off = feats_off.set_index(["station", "ts"])
    checked = 0
    for entry in pred.log:
        row = off.loc[(entry.station, entry.ts)]
        online = pd.to_numeric(entry.features.drop("station")).to_numpy(dtype=float)
        offline_vals = row[[c for c in meta.feature_names if c != "station"]].to_numpy(dtype=float)
        assert np.array_equal(np.isnan(online), np.isnan(offline_vals)), (
            f"NaN positions differ at {entry.station} {entry.ts}"
        )
        np.testing.assert_allclose(online, offline_vals, rtol=1e-5, atol=1e-5, equal_nan=True)
        checked += 1
    assert checked == n_ts * len(STATIONS)

    # predictions: online == offline model applied to the offline features
    for h in CFG["forecast"]["horizons"]:
        model = pred.models[h]
        sel = feats_off[feats_off["ts"] >= FIRST_PRED]
        sel = sel[sel["ts"] <= pd.Timestamp(END)]
        expected = predict(model, sel, meta.feature_names)
        got = {(e.station, e.ts): e.yhat[h] for e in pred.log}
        online = np.array(
            [got[(s, t)] for s, t in zip(sel["station"].astype(str), sel["ts"], strict=True)]
        )
        np.testing.assert_allclose(online, expected, rtol=1e-5, atol=1e-5)

    con = db.connect(db_path, read_only=True)
    n_rows = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    assert n_rows == n_ts * len(STATIONS) * len(CFG["forecast"]["horizons"])
    versions = {r[0] for r in con.execute("SELECT DISTINCT model_version FROM predictions")}
    assert len(versions) == 1
