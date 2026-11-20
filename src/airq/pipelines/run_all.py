"""Reproduce every result from raw data in one command (spec 15.3, gate 3).

python -m scripts.run_all --home D:/airq-repro          full run in a fresh home (hours)
python -m scripts.run_all --home D:/airq-repro --quick  QUICK run, minutes (2 stations, no Optuna)
python -m scripts.run_all --check                       only verify that the outputs exist

Stages are cached by their outputs: a stage whose output files all exist is skipped, so an
interrupted run continues. `--home` (AIRQ_HOME) keeps a reproduction away from the committed
results; a QUICK run is refused without it because it would overwrite the real results. The test
split is evaluated once per home (guard files); a fresh home never needs `--force`.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from airq.env import repo_root, resolve_home

OPTUNA_TRIALS = 20  # decision 2026-11-19 (docs/KARARLAR.md); the config carries the same number
FIGURES = [
    "architecture", "eda_corr_missing", "rq1_horizon", "rq1_ablation_loso", "rq1_shap_groups",
    "rq2_pr_lead", "rq2_haze_example", "rq3b_damage", "rq4_uncertainty",
]  # fmt: skip
TABLES = ["dataset", "rq1_main", "rq1_ablation", "rq1_loso", "rq1_extreme", "rq2_warning",
          "rq2_haze", "rq3b", "rq4_coverage", "rq4_warning"]  # fmt: skip


@dataclass(frozen=True)
class Stage:
    name: str
    script: str
    args: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()  # relative to the home; a trailing "*" counts files by prefix
    quick_args: tuple[str, ...] = ()  # appended in --quick mode
    quick_optional: tuple[str, ...] = ()  # outputs a QUICK run legitimately may not produce
    skip_in_quick: bool = False
    group: str = "core"  # core | system (long, needs broker + models)
    est: str = ""


def stages(trials: int = OPTUNA_TRIALS) -> list[Stage]:
    t, m = "reports/tables/", "reports/metrics/"
    return [
        Stage("download", "download_data", (), ("data/raw/beijing",), est="1 min"),
        Stage(
            "dataset",
            "make_dataset",
            (),
            ("data/processed/clean.parquet", t + "dataset_summary.csv", t + "episodes_test.csv"),
            ("--quick",),
            est="1 min",
        ),  # fmt: skip
        Stage("edge", "fit_edge", (), (m + "edge_params.json",), est="1 min"),
        Stage(
            "forecast_v0",
            "train_forecast",
            (),
            (m + "forecast_v0.json", "models/lgbm_h1_k0.txt"),
            ("--quick",),
            est="5 min",
        ),
        Stage(
            "tuning",
            "run_ablation",
            ("--trials", str(trials)),
            (
                m + "forecast_v1.json",
                t + "rq1_tuning.csv",
                t + "rq1_ablation_val.csv",
                "models/hparams_h24_k11.json",
            ),
            skip_in_quick=True,
            est="1-2 h",
        ),  # fmt: skip
        Stage(
            "final",
            "run_final",
            (),
            (
                m + "forecast_test.json",
                t + "rq1_main.csv",
                t + "rq1_ablation.csv",
                t + "rq1_extreme.csv",
                t + "rq1_loso.csv",
                t + "rq1_shap.csv",
                t + "rq1_stats.csv",
            ),
            ("--quick",),
            est="15 min",
        ),  # fmt: skip
        Stage(
            "warning",
            "run_warning",
            (),
            (m + "warning_test.json", t + "rq2_warning.csv", t + "rq2_haze.csv"),
            ("--quick",),
            est="5 min",
        ),  # fmt: skip
        Stage(
            "robustness",
            "run_robustness",
            (),
            (m + "rq3b_test.json", t + "rq3b_robustness.csv"),
            ("--quick",),
            est="5 min",
        ),  # fmt: skip
        Stage(
            "uncertainty",
            "run_uncertainty",
            (),
            (
                m + "uncertainty_test.json",
                t + "rq4_coverage.csv",
                t + "rq4_warning.csv",
                "models/quantile_calibration.json",
            ),
            ("--quick",),
            est="10 min",
        ),
        Stage(
            "system",
            "run_system_bench",
            ("--plan", "reduced"),
            (t + "rq3a_bench.csv",),
            skip_in_quick=True,
            group="system",
            est="1 h (needs the broker)",
        ),  # fmt: skip
        Stage(
            "scenarios",
            "run_scenarios",
            (),
            (t + "scenarios_summary.csv",),
            skip_in_quick=True,
            group="system",
            est="25 min (needs the broker)",
        ),  # fmt: skip
        Stage(
            "scenarios_ab",
            "run_scenarios",
            ("--ab",),
            (t + "scenarios_ab.csv",),
            skip_in_quick=True,
            group="system",
            est="40 min (needs the broker)",
        ),
        Stage(
            "figures",
            "make_figures",
            (),
            tuple(f"reports/figures/{f}.png" for f in FIGURES),
            quick_optional=(
                "reports/figures/rq2_haze_example.png",
            ),  # no regional haze with 2 stations
            est="1 min",
        ),
        Stage(
            "tables",
            "make_tables",
            (),
            tuple(f"paper/tables/{n}.tex" for n in TABLES),
            est="seconds",
        ),  # fmt: skip
    ]


def missing_outputs(stage: Stage, home: Path, quick: bool = False) -> list[str]:
    out = []
    for rel in stage.outputs:
        if quick and rel in stage.quick_optional:
            continue
        p = home / rel
        if rel == "data/raw/beijing":  # the 12 station files
            if len(list(p.rglob("PRSA_Data_*.csv"))) < 12 if p.exists() else True:
                out.append(f"{rel} (12 PRSA_Data_*.csv)")
        elif not p.exists():
            out.append(rel)
    return out


@dataclass
class StageResult:
    name: str
    status: str  # ran | cached | skipped | failed | missing
    seconds: float = 0.0
    missing: list[str] = field(default_factory=list)
    note: str = ""


def run_stage(stage: Stage, home: Path, quick: bool, force: bool, log_dir: Path) -> StageResult:
    args = [*stage.args, *(stage.quick_args if quick else ())]
    if force and stage.script in ("run_final", "run_warning", "run_robustness", "make_dataset"):
        args.append("--force")
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{stage.name}.log"
    t0 = time.monotonic()
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, "-m", f"scripts.{stage.script}", *args],
            cwd=repo_root(), env={**os.environ, "AIRQ_HOME": str(home), "PYTHONUNBUFFERED": "1"},
            stdout=fh, stderr=subprocess.STDOUT,
        )  # fmt: skip
    seconds = time.monotonic() - t0
    if proc.returncode != 0:
        return StageResult(stage.name, "failed", seconds, note=f"exit {proc.returncode}, see {log}")
    return StageResult(stage.name, "ran", seconds, missing_outputs(stage, home, quick))


def plan(quick: bool, with_system: bool, skip: set[str], only: set[str] | None) -> list[Stage]:
    out = []
    for s in stages():
        if only and s.name not in only:
            continue
        if (
            s.name in skip
            or (quick and s.skip_in_quick)
            or (s.group == "system" and not with_system)
        ):
            continue
        out.append(s)
    return out


def run_all(
    home: Path | None = None,
    quick: bool = False,
    with_system: bool = False,
    force: bool = False,
    check_only: bool = False,
    dry_run: bool = False,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    keep_going: bool = False,
    log=print,
) -> list[StageResult]:
    if quick and home is None and "AIRQ_HOME" not in os.environ and not check_only:
        raise SystemExit(
            "--quick would overwrite the committed results; give a separate --home DIR "
            "(a QUICK run is a smoke test of the pipeline, not a result)."
        )
    home = Path(home) if home else resolve_home()
    home.mkdir(parents=True, exist_ok=True)
    chosen = plan(quick, with_system, skip or set(), only)
    results: list[StageResult] = []
    log(f"home: {home}   mode: {'QUICK' if quick else 'FULL'}   stages: {[s.name for s in chosen]}")
    for s in chosen:
        missing = missing_outputs(s, home, quick)
        if check_only:
            res = StageResult(s.name, "missing" if missing else "cached", 0.0, missing)
        elif dry_run:
            state = "cached" if not missing and not force else "ran"
            cmd = f"scripts.{s.script} {' '.join(s.args)}".strip()
            res = StageResult(s.name, state, 0.0, note=f"would run: {cmd} ({s.est})")
        elif not missing and not force:
            res = StageResult(s.name, "cached")
        else:
            log(f"[{s.name}] running scripts.{s.script} ... (about {s.est or '?'})")
            res = run_stage(s, home, quick, force, home / "reports" / "run_all")
        results.append(res)
        log(f"[{s.name}] {res.status}  {res.seconds:.0f}s  {res.note}"
            + (f"  MISSING {res.missing}" if res.missing else ""))  # fmt: skip
        if res.status == "failed" and not keep_going:
            break
    if not (check_only or dry_run):
        write_report(home, results, quick, with_system)
    return results


def ok(results: list[StageResult]) -> bool:
    return bool(results) and all(r.status in ("ran", "cached") and not r.missing for r in results)


def write_report(home: Path, results: list[StageResult], quick: bool, with_system: bool) -> Path:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root(),
                                capture_output=True, text=True).stdout.strip()  # fmt: skip
    except OSError:
        commit = ""
    path = home / "reports" / "run_all.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "quick": quick, "with_system": with_system, "git_commit": commit,
                "python": platform.python_version(), "platform": platform.platform(),
                "stages": [r.__dict__ for r in results], "ok": ok(results),
            },
            indent=2,
        ),
        encoding="utf-8",
    )  # fmt: skip
    return path
