"""The paper stays consistent with the results.

numbers.tex is generated from reports/, main.tex passes the static checks, and every number in the
text is a macro that points at a results file."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import check_paper, make_paper_numbers  # noqa: E402


@pytest.fixture(scope="module")
def generated():
    make_paper_numbers.build()
    return make_paper_numbers.render()


def test_committed_numbers_match_the_results_files(generated):
    tex, md = generated
    assert (ROOT / "paper" / "numbers.tex").read_text(encoding="utf-8") == tex
    assert (ROOT / "paper" / "NUMBERS.md").read_text(encoding="utf-8") == md


def test_every_macro_has_a_source_file_selector_and_column(generated):
    for row in make_paper_numbers.ROWS:
        assert row["file"] and row["column"] and row["how"], row
        if row["file"].startswith("reports/"):
            assert (ROOT / row["file"]).exists(), row["file"]
        assert re.fullmatch(r"n[A-Za-z]+", row["macro"]), row["macro"]  # LaTeX: letters only


def test_macro_names_are_unique(generated):
    names = [r["macro"] for r in make_paper_numbers.ROWS]
    assert len(names) == len(set(names))


def test_the_paper_passes_the_static_checks(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_paper"])
    code = check_paper.main()
    out = capsys.readouterr().out
    assert code == 0, out


def test_figures_are_copied_next_to_the_paper():
    for name in make_paper_numbers.FIGURES:
        assert (ROOT / "paper" / "figures" / f"{name}.pdf").exists(), name


def test_the_bibliography_keys_follow_the_ek_a_numbering():
    keys = check_paper.bib_keys()
    assert {"R1", "R8", "R8d", "R13", "R15", "R26", "R27"} <= keys
    assert "R23" not in keys  # the CO2 reference of the optional P2 task is not used
