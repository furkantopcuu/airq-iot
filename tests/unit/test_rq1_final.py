import copy

import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.data.fixture import make_fixture_raw
from airq.pipelines import data as data_pipeline
from airq.pipelines.rq1_final import evaluate_test, loso, shap_groups
from airq.pipelines.tuning import run_tuning

CFG = copy.deepcopy(load_config())
CFG["forecast"]["horizons"] = [1]
CFG["forecast"]["lgbm"].update(n_estimators=40, early_stopping=8)


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    home = tmp_path_factory.mktemp("airq_home_final")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIRQ_HOME", str(home))
    make_fixture_raw(home / "data" / "raw")
    data_pipeline.run(CFG, quick=True)
    run_tuning(CFG, quick=True, trials=2, horizons=[1], ks=[0])
    yield home
    mp.undo()


def test_test_split_is_evaluated_once_and_tables_are_written(home):
    summary = evaluate_test(CFG, quick=True)
    assert summary["evaluated_on"] == "test" and summary["by_horizon_best"][1]["best_rmse"] > 0
    with pytest.raises(FileExistsError, match="already evaluated"):
        evaluate_test(CFG, quick=True)  # the guard blocks a second look at the test split
    t = home / "reports" / "tables"
    main = pd.read_csv(t / "rq1_main.csv")
    assert {"B0_persistence", "B1_seasonal_naive", "B2_ridge_k0", "M1_lgbm_k0"} <= set(
        main["model"]
    )
    assert main.loc[main["model"] == "B0_persistence", "improvement_vs_b0_pct"].iloc[0] == 0
    m1 = main[main["model"] == "M1_lgbm_k0"].iloc[0]
    assert (
        m1["ci_lo"]
        <= (main.loc[main["model"] == "B0_persistence", "rmse"].iloc[0] - m1["rmse"])
        <= m1["ci_hi"]
    )
    clean = pd.read_parquet(home / "data" / "processed" / "clean.parquet")
    n_test_rows = (clean["split"] == "test").sum()
    assert 0 < main["n"].max() <= n_test_rows  # only test rows were evaluated
    for name in (
        "rq1_ablation",
        "rq1_stats",
        "rq1_extreme",
        "rq1_breakdown",
        "rq1_by_station",
        "rq1_nowcast",
    ):
        assert (t / f"{name}.csv").exists(), name
    stats = pd.read_csv(t / "rq1_stats.csv")
    assert set(stats["station"]) == set(CFG["colab"]["quick"]["stations"])
    now = pd.read_csv(t / "rq1_nowcast.csv").iloc[0]
    assert now["h"] == 0 and now["r2"] > 0  # the same-hour control is a nowcast, not a forecast


def test_shap_group_shares_sum_to_one_hundred(home):
    out = shap_groups(CFG, quick=True, sample=300)
    sums = out.groupby("h")["share_pct"].sum()
    assert np.allclose(sums.to_numpy(), 100.0)
    assert set(out["group"]) <= {"own PM2.5 history", "co-pollutants", "meteorology", "calendar",
                                 "network (neighbors)", "other"}  # fmt: skip


def test_loso_holds_out_each_station_and_guards_against_reruns(home):
    res = loso(CFG, quick=True)
    assert set(res["station"]) == set(CFG["colab"]["quick"]["stations"]) and len(res) == 2
    assert np.isfinite(res["rmse_loso"]).all() and (res["n"] > 0).all()
    with pytest.raises(FileExistsError):
        loso(CFG, quick=True)
