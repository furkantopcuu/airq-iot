"""Run the ready-made scenarios against the REAL stack and record what actually happened (spec 9.5).

Per scenario: a private broker + edge + ingest + predictor + fleet (`--control`) as separate
processes, a ScenarioPlayer that sends the YAML steps when the simulated clock reaches them, and a
scorecard computed from the run database. The YAML `expected` list is a set of HYPOTHESES: each is
reported as confirmed / refuted / undetermined and never edited to match the outcome.

python -m scripts.run_scenarios [--only NAME] [--speedup 7200] [--force]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from airq.devices.modes import HOUR
from airq.env import resolve_paths
from airq.iot.broker import broker_reachable, start_broker
from airq.pipelines.rq3a import _drain, _free_port, _spawn
from airq.scenarios.player import PlayerThread, ScenarioPlayer, marks_for
from airq.scenarios.spec import Scenario, evaluate_expected, load_all
from airq.server import db
from airq.server.control import Controller
from airq.server.scorecard import SCORING_VERSION, scorecard
from airq.server.truth import Truth

TAIL_H = 24  # simulated hours after the scenario so the h=24 forecasts can be scored


def scenario_window(sc: Scenario) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(fleet start, time zero, fleet end) in simulated time."""
    if sc.start is None:
        raise ValueError(f"{sc.name}: run_scenarios needs a `start` date in the YAML")
    start = pd.Timestamp(sc.start)
    zero = start + sc.warmup_h * HOUR
    return start, zero, zero + (sc.duration_h + TAIL_H) * HOUR


def _sim_clock(db_path: Path):
    def clock():
        if not db_path.exists():
            return None
        try:
            con = db.connect(db_path, read_only=True)
            try:
                v = con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
            finally:
                con.close()
        except Exception:  # noqa: BLE001 - the writer may hold the file for a moment
            return None
        return None if v is None else pd.Timestamp(v)

    return clock


def run_scenario(
    cfg: dict, sc: Scenario, work: Path, truth: Truth, speedup: float = 7200.0, k_main: int = 11
) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    start, zero, end = scenario_window(sc)
    db_path, port = work / f"{sc.name}.db", _free_port()
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    broker = start_broker("127.0.0.1", port, "auto")
    for _ in range(100):
        if broker_reachable("127.0.0.1", port):
            break
        time.sleep(0.1)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    bk = f"127.0.0.1:{port}"
    procs = {
        "edge": _spawn(["airq.edge.gateway", "--broker", bk], work / f"{sc.name}.edge.log", env),
        "ingest": _spawn(
            ["airq.server.ingest", "--broker", bk, "--db", str(db_path)],
            work / f"{sc.name}.ingest.log",
            env,
        ),
        "predictor": _spawn(
            ["airq.server.predictor", "--broker", bk, "--k", str(k_main), "--db", str(db_path)],
            work / f"{sc.name}.pred.log",
            env,
        ),
    }
    time.sleep(6.0)  # services connect and subscribe before the first reading
    stations = list(cfg["data"]["stations"])
    fleet = subprocess.Popen(
        [
            sys.executable, "-m", "airq.devices.fleet", "--start", str(start), "--end", str(end),
            "--speedup", str(speedup), "--stations", "all", "--broker", bk, "--control",
        ],
        stdout=open(work / f"{sc.name}.fleet.log", "w"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
        env=env,
    )  # fmt: skip
    ctl = Controller("127.0.0.1", port, client_id="scenario-runner")
    ctl.start()
    player = ScenarioPlayer(sc, ctl, stations, zero_ts=zero)
    thread = PlayerThread(player, _sim_clock(db_path), poll_s=0.05)
    t0 = time.monotonic()
    thread.start()
    fleet.wait()
    fleet_s = time.monotonic() - t0
    thread.stop_flag.set()
    thread.join(timeout=5)
    drain_s = _drain(db_path, True, str(end), 900.0)
    ctl.stop()
    for pr in procs.values():
        pr.terminate()
    for pr in procs.values():
        try:
            pr.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pr.kill()
    broker.kill()

    con = db.connect(db_path, read_only=True)
    try:
        rows = scorecard(con, truth, list(player.marks), stations)
    finally:
        con.close()
    by_label = {r["label"]: r for r in rows}
    status = player.status()
    return {
        "scenario": sc.name,
        "description": sc.description,
        "sim_start": str(start),
        "sim_zero": str(zero),
        "sim_end": str(end),
        "speedup": speedup,
        "fleet_wall_s": round(fleet_s, 1),
        "drain_s": round(drain_s, 1),
        "steps_fired": status["steps_fired"],
        "steps_total": status["steps_total"],
        "step_log": status["log"],
        "scorecard": rows,
        "expected": evaluate_expected(sc, by_label),
        "reference": "recorded data replay (server/truth.py)",
        "scoring_version": SCORING_VERSION,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }


def run_all(
    cfg: dict,
    only: list[str] | None = None,
    speedup: float = 7200.0,
    force: bool = False,
    scenarios_dir: Path | str = "configs/scenarios",
) -> list[dict]:
    paths = resolve_paths(cfg["paths"])
    out_dir = paths["reports"] / "scenarios"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    scenarios = load_all(scenarios_dir)
    names = only or list(scenarios)
    unknown = [n for n in names if n not in scenarios]
    if unknown:
        raise SystemExit(f"unknown scenario(s) {unknown}; available: {list(scenarios)}")
    truth = Truth.from_cfg(cfg)
    results = []
    for i, name in enumerate(names, 1):
        path = out_dir / f"{name}.json"
        if path.exists() and not force:
            print(f"[{i}/{len(names)}] {name}: exists, skipped (use --force)", flush=True)
            results.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        t0 = time.monotonic()
        res = run_scenario(cfg, scenarios[name], work, truth, speedup)
        path.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        verdicts = [e["verdict"] for e in res["expected"]]
        print(
            f"[{i}/{len(names)}] {name} done in {time.monotonic() - t0:.0f}s "
            f"steps {res['steps_fired']}/{res['steps_total']} verdicts {verdicts}",
            flush=True,
        )
        results.append(res)
    write_summary(paths["reports"], results)
    return results


def rescore(
    cfg: dict, names: list[str] | None = None, scenarios_dir: Path | str = "configs/scenarios"
) -> list[dict]:
    """Score the STORED runs again (same databases, same commands) with the current scorecard.

    The previous scorecard and verdicts stay in the json as `scorecard_v<N>` / `expected_v<N>`;
    hypotheses are never touched. Used after a scoring definition was corrected.
    """
    paths = resolve_paths(cfg["paths"])
    out_dir = paths["reports"] / "scenarios"
    scenarios = load_all(scenarios_dir)
    truth = Truth.from_cfg(cfg)
    stations = list(cfg["data"]["stations"])
    results = []
    for name in names or list(scenarios):
        path, sc = out_dir / f"{name}.json", scenarios[name]
        prev = json.loads(path.read_text(encoding="utf-8"))
        old_v = prev.get("scoring_version", 1)
        if old_v == SCORING_VERSION:
            results.append(prev)
            continue
        _start, zero, _end = scenario_window(sc)
        con = db.connect(out_dir / "work" / f"{name}.db", read_only=True)
        try:
            rows = scorecard(con, truth, marks_for(sc, zero), stations)
        finally:
            con.close()
        pattern = r"(scorecard|expected)_v[2-9]"
        keep = {k: v for k, v in prev.items() if not re.fullmatch(pattern, k)}
        if old_v == 1:  # the as-run scoring stays as evidence; later versions replace each other
            keep["scorecard_v1"], keep["expected_v1"] = prev["scorecard"], prev["expected"]
        new = {
            **keep,
            "scorecard": rows,
            "expected": evaluate_expected(sc, {r["label"]: r for r in rows}),
            "scoring_version": SCORING_VERSION,
            "rescored_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(new, indent=2, default=str), encoding="utf-8")
        print(f"{name}: re-scored (v{old_v} -> v{SCORING_VERSION})", flush=True)
        results.append(new)
    write_summary(paths["reports"], results)
    return results


def write_summary(reports: Path, results: list[dict]) -> Path:
    """One row per hypothesis: what was expected, what was measured, the verdict."""
    rows = []
    for r in results:
        for e in r["expected"]:
            rows.append(
                {
                    "scenario": r["scenario"],
                    "label": e["label"],
                    "metric": e["metric"],
                    "relation": e["relation"],
                    "reference": e["reference"],
                    "measured": e["measured"],
                    "verdict": e["verdict"],
                }  # fmt: skip
            )
    path = reports / "tables" / "scenarios_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
