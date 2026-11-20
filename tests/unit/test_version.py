"""One version everywhere: pyproject, the package, the API and the changelog."""

import re
import tomllib
from pathlib import Path

import airq
from airq.server.api import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_package_api_and_changelog_agree_on_the_version():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == airq.__version__
    assert create_app(db_path=ROOT / "no.db").version == airq.__version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert first and first.group(1) == airq.__version__  # the newest entry is the current version
