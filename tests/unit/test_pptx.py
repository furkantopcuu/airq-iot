"""The presentation deck is built from the paper's numbers, has notes, and nothing overflows.

scripts/make_pptx.py describes every slide once and writes it with python-pptx. These tests build
the deck in memory (and once to a temporary file), so no binary has to match byte for byte.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pptx = pytest.importorskip("pptx")
from scripts import make_pptx  # noqa: E402

FONTS = (make_pptx.WIN_FONTS / "calibri.ttf").exists()  # text fit is measured with Calibri


@pytest.fixture(scope="module")
def deck():
    slides = make_pptx.build()
    make_pptx.attach(slides)
    return slides


def test_the_deck_has_no_layout_problems(deck):
    problems = [p for s in deck for p in s.problems]
    if not FONTS:  # without Calibri the fit is only approximate: keep the structural checks
        problems = [p for p in problems if "text needs" not in p]
    assert not problems, problems


def test_every_slide_has_speaker_notes(deck):
    assert all(s.notes.strip() for s in deck)


def test_the_skeleton_matches_the_outline(deck):
    keys = [s.key for s in deck]
    for needed in (
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "6a-1",
        "6a-2",
        "7",
        "8",
        "9",
        "10",
        "10a",
        "11",
        "12",
        "13",
    ):
        assert needed in keys, needed
    assert [k for k in keys if k.startswith("B")] == [f"B{i}" for i in range(1, 8)]
    assert len(keys) <= 25  # a 12-15 minute talk plus backups


def test_every_number_comes_from_a_macro(deck):
    values = make_pptx.make_slides.macros()
    for s in deck:
        for el in s.els:
            paras = el.paras if isinstance(el, make_pptx.Text) else []
            if isinstance(el, make_pptx.Table):
                paras = [make_pptx.P(c) for row in el.rows for c in row]
            for p in paras:
                for key in re.findall(r"\{\{(\w+)\}\}", p.text):
                    assert key in values, f"slide {s.key}: unknown placeholder {key}"
                assert "{{" not in make_pptx.num(p.text), p.text


def test_the_technical_slides_have_a_why_box(deck):
    by_key = {s.key: s for s in deck}
    for key in ("4", "5", "6", "7", "8", "9", "10", "10a"):
        texts = [
            p.text for el in by_key[key].els if isinstance(el, make_pptx.Text) for p in el.paras
        ]
        assert "NEDEN?" in texts, key
    for key in ("6a-1", "6a-2"):  # the why-table is the slide
        assert any(isinstance(el, make_pptx.Table) for el in by_key[key].els)


def test_the_written_file_opens_and_matches(deck, tmp_path, monkeypatch):
    out = tmp_path / "deck.pptx"
    make_pptx.write_pptx(deck, out)
    prs = pptx.Presentation(str(out))
    assert len(prs.slides) == len(deck)
    for s, slide in zip(deck, prs.slides, strict=True):
        assert slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip(), s.key
        for shape in slide.shapes:
            assert shape.left >= 0 and shape.top >= 0, (s.key, shape.name)
            assert shape.left + shape.width <= prs.slide_width + 1, (s.key, shape.name)
            assert shape.top + shape.height <= prs.slide_height + 1, (s.key, shape.name)
            if shape.shape_type == 13:  # picture: alt text for accessibility
                assert shape._element.nvPicPr.cNvPr.get("descr"), (s.key, shape.name)
