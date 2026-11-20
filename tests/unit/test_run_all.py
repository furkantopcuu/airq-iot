"""run_all: stage plan, caching by outputs, the QUICK safety refusal, and failure reporting."""

from pathlib import Path

import pytest

from airq.config import load_config
from airq.pipelines import run_all as ra

REPO = Path(__file__).resolve().parents[2]


def fabricate(home: Path, stage: ra.Stage) -> None:
    for rel in stage.outputs:
        p = home / rel
        if rel == "data/raw/beijing":
            p.mkdir(parents=True, exist_ok=True)
            for i in range(12):
                (p / f"PRSA_Data_{i}.csv").write_text("x")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")


def test_every_stage_points_at_an_existing_script_in_dependency_order():
    names = [s.name for s in ra.stages()]
    assert names == [
        "download", "dataset", "edge", "forecast_v0", "tuning", "final", "warning",
        "robustness", "uncertainty", "system", "scenarios", "scenarios_ab", "figures", "tables",
    ]  # fmt: skip
    for s in ra.stages():
        assert (REPO / "scripts" / f"{s.script}.py").exists(), s.script
        assert s.outputs, s.name


def test_the_optuna_budget_in_run_all_is_the_one_in_the_config():
    assert ra.OPTUNA_TRIALS == load_config()["forecast"]["optuna_trials"] == 20
    tuning = next(s for s in ra.stages() if s.name == "tuning")
    assert tuning.args == ("--trials", "20")


def test_plan_selects_by_mode_group_skip_and_only():
    full = [s.name for s in ra.plan(False, False, set(), None)]
    assert "tuning" in full and "system" not in full and "scenarios" not in full
    quick = [s.name for s in ra.plan(True, True, set(), None)]
    assert "tuning" not in quick and "system" not in quick  # slow stages never run in QUICK
    assert "scenarios" not in quick and "final" in quick
    assert [s.name for s in ra.plan(False, True, set(), None)][-5:] == [
        "system",
        "scenarios",
        "scenarios_ab",
        "figures",
        "tables",
    ]
    assert [s.name for s in ra.plan(False, False, {"tuning"}, None)].count("tuning") == 0
    assert [s.name for s in ra.plan(False, False, set(), {"edge", "final"})] == ["edge", "final"]


def test_quick_without_a_separate_home_is_refused(monkeypatch):
    monkeypatch.delenv("AIRQ_HOME", raising=False)
    with pytest.raises(SystemExit, match="overwrite"):
        ra.run_all(quick=True)
    ra.run_all(quick=True, check_only=True, home=None, log=lambda *_: None)  # checking is harmless


def test_check_reports_missing_outputs_then_passes_once_they_exist(tmp_path):
    res = ra.run_all(home=tmp_path, check_only=True, log=lambda *_: None)
    assert not ra.ok(res) and all(r.status == "missing" for r in res)
    assert "data/raw/beijing (12 PRSA_Data_*.csv)" in res[0].missing
    for s in ra.plan(False, False, set(), None):
        fabricate(tmp_path, s)
    res = ra.run_all(home=tmp_path, check_only=True, log=lambda *_: None)
    assert ra.ok(res) and {r.status for r in res} == {"cached"}


def test_cached_stages_are_skipped_and_dry_run_runs_nothing(tmp_path):
    for s in ra.plan(False, False, set(), None):
        fabricate(tmp_path, s)
    lines: list[str] = []
    res = ra.run_all(home=tmp_path, log=lines.append)  # everything cached: no subprocess started
    assert all(r.status == "cached" for r in res) and ra.ok(res)
    assert (tmp_path / "reports" / "run_all.json").exists()
    dry = ra.run_all(home=tmp_path / "empty", dry_run=True, only={"edge"}, log=lambda *_: None)
    assert dry[0].status == "ran" and "scripts.fit_edge" in dry[0].note
    assert not (tmp_path / "empty" / "reports" / "run_all.json").exists()


def test_a_failing_stage_is_reported_with_its_log_and_stops_the_run(tmp_path):
    bad = ra.Stage("boom", "no_such_script", outputs=("x.txt",))
    res = ra.run_stage(bad, tmp_path, False, False, tmp_path / "logs")
    assert res.status == "failed" and "see" in res.note
    assert (tmp_path / "logs" / "boom.log").exists()
    assert not ra.ok([res])


def test_a_quick_run_may_lack_the_haze_example_figure_but_a_full_run_may_not(tmp_path):
    figures = next(s for s in ra.stages() if s.name == "figures")
    for rel in figures.outputs:
        if rel not in figures.quick_optional:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x")
    assert ra.missing_outputs(figures, tmp_path, quick=True) == []
    assert ra.missing_outputs(figures, tmp_path, quick=False) == [
        "reports/figures/rq2_haze_example.png"
    ]
