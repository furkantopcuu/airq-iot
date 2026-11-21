"""The slide material stays consistent with the paper and the results.

Slides are generated from slides/src/*.md; their numbers come from paper/numbers.tex (generated from reports/).
"""

# ruff: noqa: E501  (comments quote TALIMAT)
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import make_slides  # noqa: E402

# slides whose title is a finding sentence with a number from the results (TALIMAT 12.1: "one message per
# slide, the title is a finding and the number in it comes from the real result")
FINDING_SLIDES = (
    "4.",
    "5.",
    "6.",
    "8.",
    "9.",
    "10.",
    "10a.",
    "12.",
    "B1.",
    "B2.",
    "B3.",
    "B4.",
    "B6.",
)
TECHNICAL_SLIDES = ("4.", "5.", "6.", "8.", "9.", "10.", "10a.")  # each carries a "Neden?" box


@pytest.fixture(scope="module")
def outline():
    return make_slides.render("outline", make_slides.macros())


def slides(text):
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    return {p.split(" ", 1)[0]: p for p in parts}


def test_committed_slides_match_their_sources():
    assert make_slides.main.__module__  # import works
    values = make_slides.macros()
    for name in make_slides.NAMES:
        assert (ROOT / "slides" / f"{name}.md").read_text(encoding="utf-8") == make_slides.render(
            name, values
        ), f"slides/{name}.md is out of date: run python -m scripts.make_slides"


def test_every_placeholder_resolves_and_no_braces_remain(outline):
    values = make_slides.macros()
    for name in make_slides.NAMES:
        text = make_slides.render(name, values)
        assert "{{" not in text and "}}" not in text, name


def test_an_unknown_placeholder_is_an_error(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "outline.src.md").write_text("## 1. x {{nNoSuchNumber}}\n", encoding="utf-8")
    monkeypatch.setattr(make_slides, "SRC", src)
    with pytest.raises(KeyError, match="nNoSuchNumber"):
        make_slides.render("outline", make_slides.macros())


def test_the_deck_has_the_skeleton_of_talimat_12_1(outline):
    keys = list(slides(outline))
    for needed in (
        "1.",
        "2.",
        "3.",
        "4.",
        "5.",
        "6.",
        "6a.",
        "7.",
        "8.",
        "9.",
        "10.",
        "11.",
        "12.",
        "13.",
    ):
        assert needed in keys, needed
    assert any(k.startswith("B") for k in keys)  # backup slides


def test_finding_slides_have_a_number_in_the_title(outline):
    s = slides(outline)
    for key in FINDING_SLIDES:
        title = s[key].splitlines()[0]
        assert re.search(r"\d", title), f"slide {key} has no number in its title: {title}"


def test_every_technical_slide_has_a_why_box(outline):
    s = slides(outline)
    for key in TECHNICAL_SLIDES:
        assert "**Neden?" in s[key], f"slide {key} has no Neden? box"


def test_the_time_budget_fits_the_talk(outline):
    total = sum(
        float(m.replace(",", "."))
        for m in re.findall(r"^\| \w+ \| [^|]+ \| ([\d,]+) \|$", outline, flags=re.M)[:-1]
    )
    assert 12 <= total <= 15, total  # 12-15 minutes without the Q&A (TALIMAT 12.0)


def test_every_referenced_figure_and_table_exists(outline):
    paths = re.findall(r"`((?:\.\./)?(?:reports|paper)/[^`\s,]+\.(?:png|md|csv))`", outline)
    assert paths
    for p in paths:
        base = ROOT / "slides" if p.startswith("../") else ROOT
        assert (base / p).resolve().exists(), p


def test_the_notes_cover_every_main_slide():
    notes = (ROOT / "slides" / "notes.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (\d+a?)\.", notes, flags=re.M)
    for n in ("1", "2", "3", "4", "5", "6", "6a", "7", "8", "9", "10", "10a", "11", "12", "13"):
        assert n in heads, n


def test_the_qa_has_the_twelve_mandatory_questions():
    qa = (ROOT / "slides" / "qa.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^## \d+\. ", qa, flags=re.M)) >= 12
    for must in ("gerçek sensör", "MQTT", "QoS 1", "Leakage", "LightGBM", "Persistence", "Aşırı olaylarda",
                 "eşiğini", "Edge'de neden tahmin", "Anomali", "güvenlik", "SQLite"):  # fmt: skip
        assert must in qa, must
