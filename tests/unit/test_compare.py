"""Comparing a reproduction with the committed reports: tolerance, exactness, exclusions."""

import json

import pandas as pd

from airq.pipelines import compare as cmp


def frame(**cols):
    return pd.DataFrame(cols)


def test_identical_tolerated_and_different_cells_are_told_apart():
    a = frame(m=["x", "y"], rmse=[1.0, 2.0], n=[3, 4])
    assert cmp.compare_frames(a, a.copy(), 1e-6, 1e-9).status == "identical"
    close = frame(m=["x", "y"], rmse=[1.0 + 1e-9, 2.0], n=[3, 4])
    d = cmp.compare_frames(a, close, 1e-6, 1e-9)
    assert d.status == "within_tolerance" and 0 < d.max_rel < 1e-6 and d.n_different == 0
    far = frame(m=["x", "y"], rmse=[1.0, 2.1], n=[3, 4])
    d = cmp.compare_frames(a, far, 1e-6, 1e-9)
    assert d.status == "different" and d.n_different == 1 and "rmse[1]" in d.worst[0]
    text = frame(m=["x", "z"], rmse=[1.0, 2.0], n=[3, 4])
    assert cmp.compare_frames(a, text, 1e-6, 1e-9).status == "different"  # text must match exactly


def test_nan_matches_nan_and_shape_changes_are_reported():
    a = frame(v=[1.0, float("nan")])
    assert cmp.compare_frames(a, a.copy(), 1e-6, 1e-9).status == "identical"
    assert cmp.compare_frames(a, frame(v=[1.0, 2.0]), 1e-6, 1e-9).status == "different"
    assert "row counts" in cmp.compare_frames(a, frame(v=[1.0]), 1e-6, 1e-9).note
    assert "columns" in cmp.compare_frames(a, frame(w=[1.0, 2.0]), 1e-6, 1e-9).note


def test_reports_comparison_skips_timing_tables_and_flags_missing_ones(tmp_path):
    for side, value in (("a", 1.0), ("b", 1.0)):
        t = tmp_path / side / "tables"
        t.mkdir(parents=True)
        frame(x=[value]).to_csv(t / "rq1_main.csv", index=False)
        frame(x=[value if side == "a" else 99.0]).to_csv(t / "rq3a_bench.csv", index=False)
    frame(x=[1]).to_csv(tmp_path / "a" / "tables" / "only_in_a.csv", index=False)
    diffs = {d.name: d.status for d in cmp.compare_reports(tmp_path / "a", tmp_path / "b")}
    assert diffs == {"only_in_a": "missing_b", "rq1_main": "identical"}  # rq3a is machine-specific
    with_timing = cmp.compare_reports(tmp_path / "a", tmp_path / "b", include_timing=True)
    assert {d.name: d.status for d in with_timing}["rq3a_bench"] == "different"
    assert "rq1_main" in cmp.summarize(with_timing)


def test_json_metrics_compare_nested_numbers_within_tolerance(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"rmse": {"h1": 17.08, "h6": [46.6, 1]}, "tag": "x"}))
    b.write_text(json.dumps({"rmse": {"h1": 17.08 + 1e-9, "h6": [46.6, 1]}, "tag": "x"}))
    assert cmp.compare_json(a, b) == []
    b.write_text(json.dumps({"rmse": {"h1": 18.0, "h6": [46.6, 1]}, "tag": "y"}))
    problems = cmp.compare_json(a, b)
    assert len(problems) == 2 and any("/rmse/h1" in p for p in problems)


def test_wall_clock_stamps_are_not_differences(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"evaluated_at": "2026-11-19T20:47:24", "rmse": 1.0}))
    b.write_text(json.dumps({"evaluated_at": "2026-11-20T13:09:31", "rmse": 1.0}))
    assert cmp.compare_json(a, b) == []
