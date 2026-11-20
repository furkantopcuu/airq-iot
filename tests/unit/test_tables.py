"""Paper / README tables are generated from the CSVs, with correct escaping and no stray numbers."""

import json
from pathlib import Path

import pandas as pd
import pytest

from airq.config import load_config
from airq.pipelines import tables as tb

REPO = Path(__file__).resolve().parents[2]
TABLES = REPO / "reports" / "tables"
needs_reports = pytest.mark.skipif(not (TABLES / "rq1_main.csv").exists(), reason="no reports")


def test_latex_escape_handles_specials_and_unicode_symbols():
    assert tb.latex_escape("a_b & 50% #1") == r"a\_b \& 50\% \#1"
    out = tb.latex_escape("RMSE (µg/m³) ≥ 150, Δ ± σ")
    assert r"\textmu g/m$^3$" in out and r"$\geq$" in out and r"$\Delta$" in out
    assert r"$\pm$" in out and r"$\sigma$" in out and "µ" not in out and "≥" not in out


def test_render_latex_is_a_booktabs_table_with_caption_and_label():
    df = pd.DataFrame({"Model": ["B0 persistence", "M2b"], "RMSE h=1": ["19.65", "17.08"]})
    tex = tb.render_latex(df, "Hata (µg/m³).", "demo")
    for part in (
        "\\toprule",
        "\\midrule",
        "\\bottomrule",
        "\\label{tab:demo}",
        "\\begin{tabular}{lr}",
    ):
        assert part in tex
    assert "B0 persistence & 19.65 \\\\" in tex and "\\caption{Hata (\\textmu g/m$^3$).}" in tex
    md = tb.render_markdown(df)
    assert md.splitlines()[0] == "| Model | RMSE h=1 |" and md.splitlines()[1] == "|---|---|"


def test_missing_values_print_as_dashes_not_nan():
    assert tb.fmt(float("nan")) == "--" and tb.fmt(None) == "--" and tb.fmt(3.14159, 3) == "3.142"


@needs_reports
def test_every_table_builds_without_nan_text_and_matches_its_csv():
    for spec in tb.TABLES:
        if not all((TABLES / f"{s}.csv").exists() for s in spec.source.split(",")):
            continue
        df = spec.build(TABLES)
        assert len(df) > 0, spec.name
        flat = " ".join(df.astype(str).to_numpy().ravel())
        assert "nan" not in flat.lower().split() and "None" not in flat, spec.name
    main = pd.read_csv(TABLES / "rq1_main.csv")
    shown = tb.t_rq1_main(TABLES).set_index("Model")
    m2b = main[(main["model"] == "M2_lgbm_k11") & (main["h"] == 24)].iloc[0]
    assert shown.loc["M2b LightGBM (k=11)", "RMSE h=24"] == f"{m2b['rmse']:.2f}"
    assert shown.loc["B0 persistence", "Δ% vs B0 h=1"] == "0.0"  # the baseline against itself


@needs_reports
def test_loso_summary_is_the_station_mean():
    loso = pd.read_csv(TABLES / "rq1_loso.csv")
    shown = tb.t_rq1_loso(TABLES)
    mean6 = loso[loso["h"] == 6]["rmse_loso"].mean()
    assert shown[shown["h"] == "6 h"]["RMSE LOSO"].iloc[0] == f"{mean6:.2f}"


def test_build_all_skips_missing_sources_and_writes_an_index(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    (tmp_path / "reports" / "tables").mkdir(parents=True)
    pd.DataFrame({"station": ["A", "ALL"], "rows": [35064, 70128], "ts_min": ["2013"] * 2,
                  "ts_max": ["2017"] * 2, "pm25_missing_pct": [2.1, 2.4], "pm25_mean": [80.0, 77.9],
                  "pm25_median": [55.0, 53.0], "pm25_p95": [240.0, 239.0]}).to_csv(
        tmp_path / "reports" / "tables" / "dataset_summary.csv", index=False)  # fmt: skip
    made = tb.build_all(load_config())
    assert list(made) == ["dataset"]  # everything else has no CSV and is skipped
    tex = (tmp_path / "paper" / "tables" / "dataset.tex").read_text(encoding="utf-8")
    assert "35 064" in tex and "70 128" in tex
    index = json.loads((tmp_path / "paper" / "tables" / "_index.json").read_text(encoding="utf-8"))
    assert index["tables"]["dataset"]["source"] == ["reports/tables/dataset_summary.csv"]


def test_readme_blocks_are_refreshed_in_place_and_idempotently(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    out = tmp_path / "paper" / "tables"
    out.mkdir(parents=True)
    (out / "demo.md").write_text("| a |\n|---|\n| 1 |\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        "intro\n<!-- TABLE:demo -->\nold\n<!-- /TABLE:demo -->\noutro\n", encoding="utf-8"
    )
    assert tb.update_readme({}, readme, ["demo", "other"]) == ["demo"]
    text = readme.read_text(encoding="utf-8")
    assert "old" not in text and "| 1 |" in text and text.startswith("intro") and "outro" in text
    tb.update_readme({}, readme, ["demo"])
    assert readme.read_text(encoding="utf-8") == text  # running it again changes nothing
