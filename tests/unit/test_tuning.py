import copy
import json

import optuna
import pandas as pd
import pytest

from airq.config import load_config
from airq.data.fixture import make_fixture_raw
from airq.pipelines import data as data_pipeline
from airq.pipelines.tuning import DEFAULT_PARAMS, run_tuning, suggest_params

CFG = copy.deepcopy(load_config())
CFG["forecast"]["lgbm"].update(n_estimators=60, early_stopping=10)  # keep the test fast


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    home = tmp_path_factory.mktemp("airq_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIRQ_HOME", str(home))
    make_fixture_raw(home / "data" / "raw")
    data_pipeline.run(CFG, quick=True)
    yield home
    mp.undo()


def test_search_space_contains_the_default_configuration():
    study = optuna.create_study()
    study.enqueue_trial(DEFAULT_PARAMS)
    study.optimize(lambda t: sum(suggest_params(t).values()) * 0.0, n_trials=1)
    got = study.trials[0].params
    assert got == pytest.approx(DEFAULT_PARAMS)  # enqueued default is inside every bound


def test_tuning_writes_artifacts_never_touches_test_and_is_resumable(home):
    res = run_tuning(CFG, quick=True, trials=3, horizons=[1], ks=[0])
    assert res["evaluated_on"] == "val" and "test" not in json.dumps(res["horizons"]).lower()
    hp = json.loads((home / "models" / "hparams_h1_k0.json").read_text())
    assert (
        hp["n_trials"] == 3 and hp["best_val_rmse"] <= hp["default_val_rmse"]
    )  # default is trial 0
    assert (home / "models" / "optuna.db").exists()
    assert (home / "models" / "lgbm_h1_k0.txt").exists()
    manifest = json.loads((home / "models" / "manifest.json").read_text())
    assert manifest["models"]["h1_k0"]["hparams_sha256"] is not None
    tuning = pd.read_csv(home / "reports" / "tables" / "rq1_tuning.csv")
    assert tuning.loc[0, "h"] == 1 and tuning.loc[0, "k"] == 0 and tuning.loc[0, "n_trials"] == 3
    assert {"num_leaves", "lambda_l2", "tuned_val_rmse"} <= set(tuning.columns)
    abl = pd.read_csv(home / "reports" / "tables" / "rq1_ablation_val.csv")
    assert {"B0_persistence", "B1_seasonal_naive", "B2_ridge_k0", "M1_lgbm_k0"} <= set(abl["model"])
    gap = res["gap_analysis"]["1"]
    assert gap["b0_rmse_val"] > 0 and "M1_lgbm_k0" in gap["models"]

    again = run_tuning(CFG, quick=True, trials=3, horizons=[1], ks=[0])  # nothing left to do
    hp2 = json.loads((home / "models" / "hparams_h1_k0.json").read_text())
    assert hp2["n_trials"] == 3 and again["trials_per_study"] == 3
    run_tuning(CFG, quick=True, trials=4, horizons=[1], ks=[0])  # resumes: exactly one more trial
    assert json.loads((home / "models" / "hparams_h1_k0.json").read_text())["n_trials"] == 4
