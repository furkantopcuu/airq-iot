"""Generate the thin notebooks (python -m scripts.build_notebooks).

Notebooks only call `airq.pipelines.*`; no business logic lives in them (spec 14.2).
They are committed WITHOUT outputs (nbstripout).
"""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

OWNER = "furkantopcuu"
REPO = f"https://github.com/{OWNER}/airq-iot.git"

PARAMS = """\
# --- parameters -------------------------------------------------------------------------
QUICK = True        # 2 stations, short run (< 5 min); set False for the full 12-station run
USE_DRIVE = False   # Colab only: mount Google Drive to keep results between sessions
RUN_OPTUNA = False  # hyper-parameter search (notebook 02 onwards)
SEEDS = [0]
"""

SETUP = f"""\
# --- setup (runs on Colab, skipped locally) ---------------------------------------------
import os
import subprocess
import sys
IN_COLAB = "google.colab" in sys.modules
REPO = "{REPO}"
if IN_COLAB:
    if not os.path.exists("/content/airq-iot"):
        subprocess.run(["git", "clone", "--depth", "1", REPO, "/content/airq-iot"], check=True)
    os.chdir("/content/airq-iot")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", ".[ml]"], check=True)
    sys.path.insert(0, "/content/airq-iot/src")  # no restart needed after the editable install
"""

ENV = """\
from airq.config import load_config
from airq.env import mount_drive_if_wanted
from airq.pipelines.colab import env_summary

mount_drive_if_wanted(USE_DRIVE)
cfg = load_config()
env_summary(cfg)
"""

EXPORT = """\
# --- export: reports/ and models/ -> airq_artifacts_<date>.zip --------------------------
from airq.pipelines.colab import export_artifacts

zip_path = export_artifacts(cfg)
print("Wrote", zip_path.name)
if IN_COLAB:
    from google.colab import files
    files.download(str(zip_path))
# locally:  python -m scripts.import_artifacts <zip>   (also runs the manifest check)
"""


def _nb(name: str, title: str, blurb: str, minutes: str, cells: list) -> None:
    head = new_markdown_cell(f"# {title}\n\n{blurb}\n\n*Estimated time: {minutes}.*")
    nb = new_notebook(
        cells=[head, new_code_cell(PARAMS), new_code_cell(SETUP), new_code_cell(ENV), *cells],
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
    )
    for i, c in enumerate(nb.cells):
        c["id"] = f"cell-{i:02d}"
    path = Path(__file__).resolve().parents[1] / "notebooks" / f"{name}.ipynb"
    path.parent.mkdir(exist_ok=True)
    nbformat.write(nb, path)
    print("wrote", path.name)


def build() -> None:
    _nb(
        "00_setup",
        "00 · Setup: data download and dataset build",
        "Downloads the Beijing dataset, verifies its SHA-256 and builds the cleaned dataset "
        "(run `pip install -e .[ml]` once beforehand). With `AIRQ_FIXTURE=1` a small "
        "synthetic dataset is used instead (CI, no internet).",
        "2-5 min (download ~8 MB)",
        [
            new_code_cell(
                """\
import pandas as pd
from airq.env import is_fixture, resolve_paths
from airq.pipelines.data import run

paths = resolve_paths(cfg["paths"])
if is_fixture():
    from airq.data.fixture import make_fixture_raw
    make_fixture_raw(paths["raw"])
else:
    from airq.data.download import download_beijing
    info = download_beijing(cfg["data"]["beijing_url"], paths["raw"] / "beijing",
                            expected_sha256=cfg["data"]["beijing_sha256"])
    print("SHA-256 verified:", info["sha256"][:16], "...")
result = run(cfg, quick=QUICK)
result
"""
            ),
            new_code_cell(
                """\
pd.read_csv(paths["reports"] / "tables" / "dataset_summary.csv")
"""
            ),
            new_code_cell(EXPORT),
        ],
    )
    _nb(
        "01_data_eda",
        "01 · Data summary, missingness and episodes",
        "Dataset summary (Table 1), station correlation and missing-data map (Figure S2) and the "
        "haze / exceedance episode counts per split.",
        "< 1 min",
        [
            new_code_cell(
                """\
import pandas as pd
from IPython.display import Image, display
from airq.env import resolve_paths
from airq.pipelines.data import run
from airq.pipelines.figures import eda

paths = resolve_paths(cfg["paths"])
if not (paths["processed"] / "clean.parquet").exists():
    raise SystemExit("Run notebook 00 first (it builds data/processed/clean.parquet).")
pd.read_csv(paths["reports"] / "tables" / "dataset_summary.csv")
"""
            ),
            new_code_cell(
                """\
pdf_png = [p for p in eda(cfg) if p.suffix == ".png"][0]
display(Image(filename=str(pdf_png)))
"""
            ),
            new_code_cell(
                """\
rows = []
for split in ("train", "val", "test"):
    ep = pd.read_csv(paths["reports"] / "tables" / f"episodes_{split}.csv")
    rows.append(ep.groupby(["type", "threshold"]).size().rename(split))
pd.concat(rows, axis=1).fillna(0).astype(int)
"""
            ),
            new_code_cell(EXPORT),
        ],
    )
    _nb(
        "02_forecast_rq1",
        "02 · RQ1: forecasting, neighbor ablation, LOSO, SHAP",
        "Baselines (persistence, seasonal-naive, Ridge) and LightGBM with 0 / 3 / 11 neighbor "
        "stations; Diebold-Mariano, Holm, Wilcoxon and block-bootstrap statistics; "
        "leave-one-station-out; TreeSHAP group shares. QUICK mode skips Optuna (default "
        "hyper-parameters). The TEST split is evaluated once in a full run; quick runs are demos "
        "and may be repeated.",
        "QUICK: 3-6 min; full run with Optuna: hours (resumable)",
        [
            new_code_cell(
                """from airq.pipelines.rq1 import run_v0
from airq.pipelines.rq1_final import evaluate_test, loso, shap_groups
from airq.pipelines.tuning import run_tuning

if RUN_OPTUNA:
    run_tuning(cfg, quick=QUICK, trials=20)  # TPE on validation only, resumable
else:
    run_v0(cfg, quick=QUICK)  # default hyper-parameters, validation only
"""
            ),
            new_code_cell(
                """summary = evaluate_test(cfg, quick=QUICK, force=QUICK)  # full run: seen once
shap_groups(cfg, quick=QUICK)
loso(cfg, quick=QUICK, force=QUICK)
summary["by_horizon_best"]
"""
            ),
            new_code_cell(
                """import pandas as pd
from IPython.display import Image, display
from airq.env import resolve_paths
from airq.pipelines.figures import rq1

paths = resolve_paths(cfg["paths"])
tables = paths["reports"] / "tables"
display(pd.read_csv(tables / "rq1_main.csv").round(2))
display(pd.read_csv(tables / "rq1_ablation.csv").round(2))
for p in rq1(cfg):
    if p.suffix == ".png":
        display(Image(filename=str(p)))
"""
            ),
            new_code_cell(EXPORT),
        ],
    )
    _nb(
        "03_early_warning_rq2",
        "03 · RQ2: early warning, lead time and haze episodes",
        "Warning rule yhat > theta - delta (delta chosen on validation by F2, 6 h cooldown), "
        "hourly precision/recall/PR-AUC, event recall and horizon-matched lead time, regional "
        "haze episodes. Run notebook 02 first (it creates the models). The TEST split is "
        "evaluated once in a full run; quick runs are demos.",
        "QUICK: 1-2 min",
        [
            new_code_cell(
                """from airq.pipelines.rq2 import run_rq2

summary = run_rq2(cfg, quick=QUICK, force=QUICK)  # full run: guarded, test is seen once
summary["n_test_exceedance_events"]
"""
            ),
            new_code_cell(
                """import pandas as pd
from IPython.display import Image, display
from airq.env import resolve_paths
from airq.pipelines.figures import rq2

paths = resolve_paths(cfg["paths"])
tables = paths["reports"] / "tables"
w = pd.read_csv(tables / "rq2_warning.csv")
cols = ["grid", "method", "theta", "h", "delta", "precision", "recall", "f2", "pr_auc",
        "m_event_recall", "m_lead_median", "false_alarm_rate"]
display(w[w["grid"] == "spec"][cols].round(3))
display(pd.read_csv(tables / "rq2_haze.csv").round(3))
for p in rq2(cfg):
    if p.suffix == ".png":
        display(Image(filename=str(p)))
"""
            ),
            new_code_cell(EXPORT),
        ],
    )
    _nb(
        "04_robustness_rq3b",
        "04 · RQ3b: faulty sensor inputs and the edge filter",
        "Synthetic faults (spike, stuck, dropout; Ni et al. / Sharma et al. taxonomy) are injected "
        "into the TEST inputs; three conditions are compared: clean, faulty with the edge filter "
        "off, faulty with the edge filter on. Targets are never touched. This measures forecast "
        "robustness, not fault-detection quality. Run notebooks 02 and 03 first.",
        "QUICK: 1-2 min (1 seed); full: about 3 min per 5 seeds",
        [
            new_code_cell(
                """from airq.pipelines.edge import run as fit_edge
from airq.pipelines.rq3b import run_rq3b

fit_edge(cfg)  # edge thresholds fitted on train
summary = run_rq3b(cfg, quick=QUICK, seeds=SEEDS, force=QUICK)  # full run: guarded
summary["persistence_coverage"]
"""
            ),
            new_code_cell(
                """import pandas as pd
from IPython.display import Image, display
from airq.env import resolve_paths
from airq.pipelines.figures import rq3b

tables = resolve_paths(cfg["paths"])["reports"] / "tables"
rob = pd.read_csv(tables / "rq3b_robustness.csv")
display(rob[rob["scope"].isin(["all", "affected"])].round(2))
display(pd.read_csv(tables / "rq3b_detection.csv").round(2))
for p in rq3b(cfg):
    if p.suffix == ".png":
        display(Image(filename=str(p)))
"""
            ),
            new_code_cell(EXPORT),
        ],
    )

    _nb(
        "05_uncertainty_rq4",
        "05 · RQ4: forecast uncertainty and q90-based warning",
        "LightGBM quantile models (alpha 0.1 / 0.5 / 0.9) give a [q10, q90] interval per "
        "horizon; a single widening factor is fitted on VALIDATION when the coverage is clearly "
        "off the 0.80 target. The test split is evaluated once. The q90 forecast then replaces "
        "the point forecast in the RQ2 warning rule. Run notebooks 02 and 03 first.",
        "QUICK: 2-4 min",
        [
            new_code_cell(
                """from airq.pipelines.rq4 import run_uncertainty

summary = run_uncertainty(cfg, quick=QUICK, force=QUICK)  # full run: guarded, test is seen once
summary["scales"]
"""
            ),
            new_code_cell(
                """import pandas as pd
from IPython.display import Image, display
from airq.env import resolve_paths
from airq.pipelines.figures import rq4

tables = resolve_paths(cfg["paths"])["reports"] / "tables"
display(pd.read_csv(tables / "rq4_coverage.csv").round(3))
display(pd.read_csv(tables / "rq4_calibration.csv").round(3))
for p in rq4(cfg):
    if p.suffix == ".png":
        display(Image(filename=str(p)))
"""
            ),
            new_code_cell(EXPORT),
        ],
    )
    _nb(
        "06_figures_tables",
        "06 · Figures and tables",
        "Builds every paper figure (vector PDF + 200 dpi PNG) and every LaTeX / Markdown table "
        "from what the earlier notebooks wrote to reports/. Anything whose inputs are missing is "
        "skipped with a note. The RQ3a system benchmark and the scenario runs exist only after a "
        "LOCAL run (broker, device fleet); import them with scripts.import_artifacts and re-run "
        "this notebook.",
        "about 1 min",
        [
            new_code_cell(
                """from IPython.display import Image, display
from airq.pipelines.figures import make_all

made, skipped = make_all(cfg)
for stage, why in skipped.items():
    print(f"skipped {stage}: {why}")
for p in made:
    if p.suffix == ".png":
        display(Image(filename=str(p)))
"""
            ),
            new_code_cell(
                """from IPython.display import Markdown, display
from airq.env import resolve_home
from airq.pipelines.tables import build_all

made_tables = build_all(cfg)  # paper/tables/*.tex and *.md from reports/tables/*.csv
for name, files in made_tables.items():
    display(Markdown(f"**{name}**\\n\\n" + files[1].read_text(encoding="utf-8")))
print("LaTeX tables in", resolve_home() / "paper" / "tables")
"""
            ),
            new_code_cell(EXPORT),
        ],
    )


if __name__ == "__main__":
    build()
