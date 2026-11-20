"""Release assets: packing, checksum-verified download, zip-slip protection."""

import zipfile

import pytest

from airq.pipelines import release as rel


def make_models(tmp_path):
    m = tmp_path / "src_models"
    m.mkdir()
    (m / "lgbm_h1_k11.txt").write_text("tree")
    (m / "manifest.json").write_text("{}")
    (m / "optuna.db").write_bytes(b"db")  # not part of the release
    (m / "notes.md").write_text("x")
    return m


def local_downloader(files):
    def download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[url.rsplit("/", 1)[1]].read_bytes())

    return download


def config(models_zip, demo, sha_models=None, sha_demo=None):
    return {
        "tag": "v9.9.9",
        "base_url": "https://example.invalid/dl",
        "assets": {
            "airq_models.zip": {
                "kind": "models",
                "sha256": sha_models or rel.sha256_file(models_zip),
            },
            "demo_recorded.db": {
                "kind": "demo",
                "dest": "data/demo_recorded.db",
                "sha256": sha_demo or rel.sha256_file(demo),
            },
        },
    }


@pytest.fixture
def assets(tmp_path):
    z = tmp_path / "airq_models.zip"
    names = rel.build_models_zip(make_models(tmp_path), z)
    demo = tmp_path / "demo_recorded.db"
    demo.write_bytes(b"sqlite")
    return z, demo, names


def test_models_zip_holds_models_and_metadata_but_not_the_optuna_database(assets):
    z, _demo, names = assets
    assert sorted(names) == ["lgbm_h1_k11.txt", "manifest.json"]
    with zipfile.ZipFile(z) as f:
        assert sorted(f.namelist()) == ["models/lgbm_h1_k11.txt", "models/manifest.json"]


def test_fetch_verifies_the_checksum_and_places_models_and_the_demo_db(assets, tmp_path):
    z, demo, _ = assets
    home = tmp_path / "home"
    placed = rel.fetch(
        config(z, demo), home=home, downloader=local_downloader({z.name: z, demo.name: demo})
    )
    assert (home / "models" / "lgbm_h1_k11.txt").read_text() == "tree"
    assert (home / "data" / "demo_recorded.db").read_bytes() == b"sqlite"
    assert len(placed) == 3
    only = rel.fetch(
        config(z, demo), only="demo", home=tmp_path / "h2",
        downloader=local_downloader({z.name: z, demo.name: demo}),
    )  # fmt: skip
    assert [p.name for p in only] == ["demo_recorded.db"]


def test_a_wrong_checksum_is_refused_and_nothing_is_installed(assets, tmp_path):
    z, demo, _ = assets
    home = tmp_path / "home"
    bad = config(z, demo, sha_models="0" * 64)
    with pytest.raises(rel.ChecksumError, match="mismatch"):
        rel.fetch(bad, home=home, downloader=local_downloader({z.name: z, demo.name: demo}))
    assert not (home / "models").exists()


def test_an_unbuilt_release_without_checksums_is_refused(assets, tmp_path):
    z, demo, _ = assets
    cfg = config(z, demo)
    cfg["assets"]["airq_models.zip"]["sha256"] = "TODO"
    with pytest.raises(rel.ChecksumError, match="no checksum"):
        rel.fetch(cfg, home=tmp_path / "h", downloader=local_downloader({}))


def test_zip_slip_is_refused(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as f:
        f.writestr("../outside.txt", "x")
    with pytest.raises(ValueError, match="unsafe"):
        rel.safe_unzip(evil, tmp_path / "target")
    assert not (tmp_path / "outside.txt").exists()


def test_the_shipped_release_config_names_both_assets():
    cfg = rel.load_release_config()
    assert set(cfg["assets"]) == {"airq_models.zip", "demo_recorded.db"}
    assert cfg["tag"].startswith("v") and cfg["base_url"].startswith("https://github.com/")
