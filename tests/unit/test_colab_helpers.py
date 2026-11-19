import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from airq.config import load_config
from airq.data.download import download_beijing, sha256_file
from airq.data.fixture import FIXTURE_STATIONS, make_fixture_raw
from airq.env import is_fixture, resolve_home
from airq.eval.figures import corr_and_missing
from airq.pipelines import data as data_pipeline
from airq.pipelines.colab import check_manifest, env_summary, export_artifacts, import_artifacts

CFG = load_config()


def test_fixture_mode_uses_a_temp_dir_and_never_the_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("AIRQ_HOME", raising=False)
    monkeypatch.setenv("AIRQ_FIXTURE", "1")
    assert is_fixture() and "airq-fixture" in str(resolve_home())
    monkeypatch.setenv("AIRQ_FIXTURE", "0")
    assert not is_fixture()
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    monkeypatch.setenv("AIRQ_FIXTURE", "1")
    assert resolve_home() == tmp_path  # an explicit AIRQ_HOME wins


def test_fixture_data_runs_through_the_real_data_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    csv_dir = make_fixture_raw(
        tmp_path / "data" / "raw", start="2013-03-01", end="2017-02-28 23:00"
    )
    assert len(list(csv_dir.glob("PRSA_Data_*.csv"))) == len(FIXTURE_STATIONS)
    res = data_pipeline.run(CFG, quick=True)  # 2 stations
    clean = pd.read_parquet(tmp_path / "data" / "processed" / "clean.parquet")
    assert set(clean["station"]) == set(CFG["colab"]["quick"]["stations"])
    assert res["rows"] == len(clean) == 2 * 35064
    assert (tmp_path / "reports" / "tables" / "dataset_summary.csv").exists()
    assert (tmp_path / "reports" / "repro.json").exists()


def test_download_rejects_a_file_with_the_wrong_hash(tmp_path):
    raw = tmp_path / "beijing"
    raw.mkdir()
    zip_path = raw / "beijing_multi_site.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("PRSA_Data_x.csv", "a,b\n1,2\n")
    assert len(sha256_file(zip_path)) == 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_beijing("http://unused.invalid", raw, expected_sha256="0" * 64)


def test_export_then_import_round_trip_and_manifest_check(monkeypatch, tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    monkeypatch.setenv("AIRQ_HOME", str(src))
    (src / "reports" / "tables").mkdir(parents=True)
    (src / "reports" / "tables" / "t.csv").write_text("a\n1\n")
    (src / "models").mkdir()
    (src / "models" / "lgbm_h1_k0.txt").write_text("model")
    (src / "models" / "manifest.json").write_text(
        json.dumps({"lightgbm_version": "4.7.0", "models": {"h1_k0": {"file": "lgbm_h1_k0.txt"}}})
    )
    zip_path = export_artifacts(CFG, out_dir=tmp_path)
    assert zip_path.name.startswith("airq_artifacts_")
    monkeypatch.setenv("AIRQ_HOME", str(dst))
    written = import_artifacts(zip_path, CFG)
    assert "reports/tables/t.csv" in written and (dst / "models" / "lgbm_h1_k0.txt").exists()


def test_import_ignores_paths_outside_reports_and_models(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path / "home"))
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", "x")
        zf.writestr("reports/../../escape2.txt", "x")
        zf.writestr("other/file.txt", "x")
        zf.writestr("reports/ok.txt", "ok")
    assert import_artifacts(evil, CFG) == ["reports/ok.txt"]
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "escape2.txt").exists()


def test_manifest_check_detects_missing_model_file_and_major_mismatch(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"lightgbm_version": "4.1.0", "models": {"h1_k0": {"file": "nope.txt"}}})
    )
    with pytest.raises(FileNotFoundError, match="missing model files"):
        check_manifest(tmp_path)
    (tmp_path / "nope.txt").write_text("m")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"lightgbm_version": "3.3.5", "models": {"h1_k0": {"file": "nope.txt"}}})
    )
    with pytest.raises(RuntimeError, match="major version"):
        check_manifest(tmp_path)


def test_env_summary_reports_versions_and_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    s = env_summary(CFG)
    assert s["is_colab"] is False and s["cpu_count"] >= 1 and s["python"].startswith("3.")


def test_eda_figure_writes_pdf_and_png(tmp_path):
    ts = pd.date_range("2016-01-01", periods=24 * 90, freq="h")
    rng = np.random.default_rng(0)
    rows = []
    for st in ("A", "B", "C"):
        d = pd.DataFrame({"station": st, "ts": ts, "pm25_raw": rng.normal(80, 20, len(ts))})
        d.loc[rng.random(len(ts)) < 0.05, "pm25_raw"] = np.nan
        rows.append(d)
    paths = corr_and_missing(pd.concat(rows), tmp_path)
    assert {p.suffix for p in paths} == {".pdf", ".png"}
    assert all(p.stat().st_size > 1000 for p in paths)
