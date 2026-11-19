import subprocess
import sys
import time

import psutil
import pytest

from airq.pipelines.rq3a import Run, _Sampler, plan_runs, window


def test_sampler_counts_child_processes_of_a_launcher():
    """A parent that only waits, with a busy CHILD: the family must show the child's CPU/RSS."""
    code = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'while True: pass']);"
        "time.sleep(30)"
    )
    parent = subprocess.Popen([sys.executable, "-c", code])
    try:
        time.sleep(1.5)  # the child exists
        sampler = _Sampler({"svc": psutil.Process(parent.pid)}, period_s=0.2)
        sampler.start()
        time.sleep(2.0)
        sampler.stop_flag.set()
        sampler.join(timeout=3)
        out = sampler.summary()
        assert out["cpu_mean_svc"] > 30  # the busy child is counted (the parent alone is ~0)
        assert out["rss_mb_svc"] > 10
    finally:
        for p in psutil.Process(parent.pid).children(recursive=True):
            p.kill()
        parent.kill()


def test_plans_have_the_documented_sizes_and_unique_keys():
    for name, n in (("smoke", 1), ("reduced", 23), ("full", 57)):
        runs = plan_runs(name)
        assert len(runs) == n and len({r.key for r in runs}) == n
    reduced = plan_runs("reduced")
    assert sum(r.speedup == 3600 for r in reduced) == 4
    assert sorted({r.offline_k for r in reduced}) == [0, 1, 3, 6]
    assert Run("p", 36000.0, 0.1, 200.0).key == "p|36000|0.1|200|0|0"
    with pytest.raises(ValueError):
        plan_runs("nope")


def test_window_is_14_days_ending_48_hours_after_the_largest_haze_onset(tmp_path):
    import pandas as pd

    (tmp_path / "tables").mkdir()
    pd.DataFrame(
        {
            "type": ["regional_haze", "regional_haze", "exceedance"],
            "station": ["ALL", "ALL", "A"],
            "threshold": [150, 150, 75],
            "start": ["2017-01-04 15:00", "2016-11-01 00:00", "2016-12-01 00:00"],
            "end": ["2017-01-07 14:00", "2016-11-01 07:00", "2016-12-01 05:00"],
            "hours": [71, 8, 6],
            "peak": [586, 160, 90],
        }
    ).to_csv(tmp_path / "tables" / "episodes_test.csv", index=False)
    start, end, onset = window({}, tmp_path, days=14)
    assert onset == pd.Timestamp("2017-01-04 15:00") and pd.Timestamp(end) == onset + pd.Timedelta(
        hours=48
    )
    assert pd.Timestamp(end) - pd.Timestamp(start) == pd.Timedelta(hours=14 * 24 - 1)
