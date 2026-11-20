"""RQ4 end to end on the synthetic fixture dataset (no network, temp home, a few minutes)."""

import json

import pandas as pd
import pytest

from airq.config import load_config
from airq.data.fixture import make_fixture_raw
from airq.env import resolve_paths
from airq.pipelines.data import run as run_data
from airq.pipelines.rq1 import run_v0
from airq.pipelines.rq4 import run_uncertainty

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def fixture_home(tmp_path_factory):
    home = tmp_path_factory.mktemp("rq4")
    mp = pytest.MonkeyPatch()
    mp.setenv("AIRQ_HOME", str(home))
    cfg = load_config()
    paths = resolve_paths(cfg["paths"])
    make_fixture_raw(paths["raw"])
    run_data(cfg, quick=True)
    run_v0(cfg, quick=True)
    yield cfg, paths
    mp.undo()


def test_uncertainty_pipeline_writes_every_output_once(fixture_home):
    cfg, paths = fixture_home
    summary = run_uncertainty(cfg, quick=True)
    tables, metrics = paths["reports"] / "tables", paths["reports"] / "metrics"
    for name in ("rq4_val", "rq4_coverage", "rq4_by_station", "rq4_by_band", "rq4_calibration",
                 "rq4_warning", "rq4_haze", "rq4_delta_val"):  # fmt: skip
        assert (tables / f"{name}.csv").exists(), name
    assert (metrics / "uncertainty_test.json").exists()
    assert (paths["models"] / "quantile_calibration.json").exists()
    assert set(summary["scales"]) == {"1", "6", "24"}
    cov = pd.read_csv(tables / "rq4_coverage.csv")
    assert set(cov["variant"]) == {"raw", "calibrated"} and set(cov["h"]) == {1, 6, 24}
    assert cov["coverage"].between(0, 1).all()
    for h in (1, 6, 24):  # the calibrated interval is never narrower than the raw one it widens
        row = cov[(cov["h"] == h) & (cov["subset"] == "all")].set_index("variant")
        if summary["scales"][str(h)] >= 1.0:
            assert row.loc["calibrated", "mean_width"] >= row.loc["raw", "mean_width"] - 1e-9
    warn = pd.read_csv(tables / "rq4_warning.csv")
    assert {"M3_q90_raw", "M3_q90_cal", "B0_persistence"} <= set(warn["method"])
    # RQ2's own outputs were not touched by the tagged evaluation
    assert not (metrics / "warning_test.json").exists()
    assert not (tables / "rq2_warning.csv").exists()


def test_a_second_evaluation_on_the_test_split_is_refused(fixture_home):
    cfg, paths = fixture_home
    with pytest.raises(FileExistsError, match="already evaluated"):
        run_uncertainty(cfg, quick=True)
    guard = json.loads((paths["reports"] / "metrics" / "uncertainty_test.json").read_text())
    assert guard["evaluated_on"] == "test" and guard["target_coverage"] == 0.8
