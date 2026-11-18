from pathlib import Path

from airq.config import config_hash, load_config
from airq.env import is_colab, resolve_paths


def test_not_colab_locally():
    assert is_colab() is False


def test_default_config_loads_and_splits_are_ordered():
    cfg = load_config()
    assert cfg["forecast"]["horizons"] == [1, 6, 24]
    assert cfg["split"]["train"][1] < cfg["split"]["val"][0]
    assert cfg["split"]["val"][1] < cfg["split"]["test"][0]
    assert len(cfg["data"]["stations"]) == 12


def test_config_hash_is_stable():
    cfg = load_config()
    assert config_hash(cfg) == config_hash(load_config())


def test_resolve_paths_honours_airq_home(monkeypatch, tmp_path):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    paths = resolve_paths({"raw": "data/raw"})
    assert paths["raw"] == Path(tmp_path) / "data/raw"
