import copy
import json

import pandas as pd
import pytest

from airq.config import load_config
from airq.data.fixture import make_fixture_raw
from airq.pipelines import data as data_pipeline
from airq.pipelines.rq2 import run_rq2
from airq.pipelines.tuning import run_tuning

CFG = copy.deepcopy(load_config())
CFG["forecast"]["horizons"] = [1]
CFG["forecast"]["lgbm"].update(n_estimators=40, early_stopping=8)


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    home = tmp_path_factory.mktemp("airq_home_rq2")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIRQ_HOME", str(home))
    make_fixture_raw(home / "data" / "raw")
    data_pipeline.run(CFG, quick=True)
    run_tuning(CFG, quick=True, trials=2, horizons=[1], ks=[0])
    yield home
    mp.undo()


def test_warning_pipeline_selects_delta_on_val_and_evaluates_test_once(home):
    summary = run_rq2(CFG, quick=True)
    assert summary["evaluated_on"] == "test"
    with pytest.raises(FileExistsError, match="already evaluated"):
        run_rq2(CFG, quick=True)  # the guard blocks a second look at the test split
    t = home / "reports" / "tables"
    w = pd.read_csv(t / "rq2_warning.csv")
    assert {"spec", "wide"} == set(w["grid"]) and {"B0_persistence", "M1_lgbm_k0"} <= set(
        w["method"]
    )
    spec_grid = set(CFG["warning"]["delta_grid"])
    wide_grid = spec_grid | set(range(0, 101, 10))
    for _, r in w[w["h"] != "any"].iterrows():
        assert r["delta"] in (spec_grid if r["grid"] == "spec" else wide_grid)
        assert 0 <= r["precision"] <= 1 and 0 <= r["recall"] <= 1 and 0 <= r["pr_auc"] <= 1
        # the horizon-matched definition is stricter than "any alert in the last 24 h"
        assert r["m_event_recall"] <= r["event_recall"] + 1e-9
    val = pd.read_csv(t / "rq2_delta_val.csv")
    best = val[val["chosen"]].groupby(["grid", "method", "theta", "h"])["fbeta"].max()
    for key in best.xs("spec", level="grid").index:
        assert (
            best[("wide", *key)] >= best[("spec", *key)] - 1e-12
        )  # wider grid never lowers val F2
    th = json.loads((home / "reports" / "metrics" / "warning_thresholds.json").read_text())
    assert set(th) == {"spec", "wide"} and th["wide"]["M1_lgbm_k0"]["150"]["1"] >= 0
    assert (home / "models" / "warning_thresholds.json").exists()
    for name in ("rq2_haze", "rq2_lead_hist", "rq2_pr_curve"):
        assert (t / f"{name}.csv").exists(), name
