import copy
import json

import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.data.fixture import make_fixture_raw
from airq.pipelines import data as data_pipeline
from airq.pipelines import edge as edge_pipeline
from airq.pipelines.rq2 import run_rq2
from airq.pipelines.rq3b import _last_fault, run_rq3b
from airq.pipelines.tuning import run_tuning

CFG = copy.deepcopy(load_config())
CFG["forecast"]["horizons"] = [1]
CFG["forecast"]["lgbm"].update(n_estimators=40, early_stopping=8)


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    home = tmp_path_factory.mktemp("airq_home_rq3b")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIRQ_HOME", str(home))
    make_fixture_raw(home / "data" / "raw")
    data_pipeline.run(CFG, quick=True)
    run_tuning(CFG, quick=True, trials=2, horizons=[1], ks=[0])
    edge_pipeline.run(CFG)
    run_rq2(CFG, quick=True)  # writes warning_thresholds.json used by RQ3b
    yield home
    mp.undo()


def test_fault_window_marks_rows_whose_last_24_hours_contain_a_fault():
    mask = np.zeros(60, dtype=np.int8)
    mask[10:13] = 2  # stuck
    mask[40] = 1  # spike
    affected, kind = _last_fault(mask, [(0, 30), (30, 60)])  # two stations of 30 hours each
    assert not affected[:10].any()
    assert affected[10:30].all() and (kind[10:30] == 2).all()  # stuck: until the station's end
    assert not affected[30:40].any()  # the window never crosses into the next station
    assert affected[40:].all() and (kind[40:] == 1).all()  # spike at row 40


def test_rq3b_reports_robustness_detection_and_guards_the_test_inputs(home):
    summary = run_rq3b(CFG, quick=True, seeds=[0, 1])
    assert summary["seeds"] == [0, 1] and "synthetic" in summary["note"]
    with pytest.raises(FileExistsError, match="already run"):
        run_rq3b(CFG, quick=True, seeds=[0])
    t = home / "reports" / "tables"
    rob = pd.read_csv(t / "rq3b_robustness.csv")
    assert {"B0_persistence", "M1_lgbm_k0"} <= set(rob["method"])
    allrows = rob[rob["scope"] == "all"]
    assert (allrows["rmse_edge_off"] >= allrows["rmse_clean"] - 1e-9).all()  # faults never help
    aff = rob[rob["scope"] == "affected"]
    assert (aff["n"] < allrows["n"].max()).all()  # the affected rows are a subset
    m1 = allrows[allrows["method"] == "M1_lgbm_k0"].iloc[0]
    assert m1["damage_off"] >= 0 and np.isfinite(m1["rmse_edge_on"])
    det = pd.read_csv(t / "rq3b_detection.csv").set_index("type")
    assert {"spike", "stuck", "dropout", "clean_test_hours"} <= set(det.index)
    assert det.loc["dropout", "hours_flagged"] == 0  # a missing value is not a value fault
    assert 0 <= det.loc["spike", "hours_flagged_pct"] <= 100
    assert det.loc["clean_test_hours", "hours_flagged_pct"] < 3  # few false alarms on clean data
    warn = pd.read_csv(t / "rq3b_warning.csv")
    assert set(warn["condition"]) == {"clean", "edge_off", "edge_on"}
    assert warn["f2"].between(0, 1).all()
    meta = json.loads((home / "reports" / "metrics" / "rq3b_test.json").read_text())
    assert meta["persistence_coverage"]["clean"] > 0.9
