"""Demo helpers (no broker needed) and the consistency between the demo config and the scenarios."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import psutil
import pytest

from airq.config import load_config
from airq.pipelines import demo
from airq.scenarios.spec import load_all

REPO = Path(__file__).resolve().parents[2]


def test_demo_config_matches_the_haze_replay_scenario():
    cfg = load_config()["demo"]
    haze = load_all(REPO / "configs" / "scenarios")["gercek_haze_replay"]
    assert pd.Timestamp(cfg["start"]) == pd.Timestamp(haze.start)
    assert cfg["warmup_h"] == haze.warmup_h  # the predictor needs 168 + 72 h of history
    assert cfg["warmup_speedup"] > cfg["speedup"] > 0
    flow = set(cfg["scenario_flow"])
    assert flow <= set(load_all(REPO / "configs" / "scenarios"))  # every planned step exists
    assert len(cfg["scenario_flow"]) == 4  # haze replay, stuck, offline, network (spec 12.2 A)


def test_port_helpers_and_wait_for():
    port = demo.free_port()
    assert not demo.port_open("127.0.0.1", port)
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        assert demo.port_open("127.0.0.1", port)
    calls = []
    assert demo.wait_for(lambda: calls.append(1) or len(calls) >= 3, 5, every_s=0.01)
    assert not demo.wait_for(lambda: False, 0.1, every_s=0.01)
    attempts = []

    def flaky():  # an exception means "not ready yet", not a crash
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("not up")
        return True

    assert demo.wait_for(flaky, 2, every_s=0.01) and len(attempts) == 3


def test_commands_are_module_invocations_with_the_chosen_ports():
    assert demo.api_args(8123)[:3] == ["uvicorn", "airq.server.api:app", "--host"]
    assert "8123" in demo.api_args(8123)
    dash = demo.dashboard_args(8600)
    assert dash[:2] == ["streamlit", "run"] and dash[dash.index("--server.port") + 1] == "8600"
    assert Path(dash[2]).name == "app.py" and "--server.headless" in dash
    fleet = demo.fleet_args("2016-12-23 16:00", "2017-01-06 15:00", 20000, "127.0.0.1:1883")
    assert fleet[0] == "airq.devices.fleet" and "--control" in fleet
    assert fleet[fleet.index("--speedup") + 1] == "20000"
    assert demo.flow_text(["a", "b"]) == "    1. a\n    2. b"


def test_pick_recorded_db_prefers_explicit_then_demo_then_scenario_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    cfg = {"paths": {"db": "data/airq.db", "reports": "reports"}}
    assert demo.pick_recorded_db(None, cfg) is None
    assert demo.pick_recorded_db("x.db", cfg) == Path("x.db")
    work = tmp_path / "reports" / "scenarios" / "work"
    work.mkdir(parents=True)
    (work / "gercek_haze_replay.db").write_bytes(b"x")
    assert demo.pick_recorded_db(None, cfg).name == "gercek_haze_replay.db"
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "demo.db").write_bytes(b"x")
    assert demo.pick_recorded_db(None, cfg).name == "demo.db"  # the demo's own run wins
    (tmp_path / "data" / "demo.db").write_bytes(b"")  # an empty file is not a recording
    assert demo.pick_recorded_db(None, cfg).name == "gercek_haze_replay.db"


def test_stack_stop_kills_the_whole_process_tree(tmp_path):
    stack = demo.Stack(tmp_path)
    code = (
        "import subprocess,sys,time;"
        "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print(c.pid,flush=True);time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    stack.procs["parent"] = proc
    child_pid = int(proc.stdout.readline())
    assert psutil.pid_exists(child_pid)
    stack._logs = []
    stack.stop()
    time.sleep(0.5)
    assert proc.poll() is not None
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == "zombie"


needs_data = pytest.mark.skipif(
    not list((REPO / "data" / "raw").rglob("PRSA_Data_*.csv")), reason="raw data not downloaded"
)


@pytest.mark.broker
@pytest.mark.slow
@needs_data
def test_smoke_runs_the_real_stack_and_a_command_through_the_http_api():
    result = demo.smoke(load_config())
    assert result["ok"] and result["command_status"] == 200 and result["command_ok"] is True
    assert result["readings_300"] >= 1  # the intervention reached the database (value or flag)


def test_the_release_recording_is_used_when_there_is_no_live_demo_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    cfg = {"paths": {"db": "data/airq.db", "reports": "reports"}}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "demo_recorded.db").write_bytes(b"x")
    assert demo.pick_recorded_db(None, cfg).name == "demo_recorded.db"
    (tmp_path / "data" / "demo.db").write_bytes(b"x")
    assert demo.pick_recorded_db(None, cfg).name == "demo.db"  # a fresh live run still wins


def test_missing_inputs_name_the_command_that_provides_them(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    cfg = load_config()
    missing = demo.missing_inputs(cfg, models=True)
    assert len(missing) == 2
    assert "download_data" in missing[0] and "fetch_release --only models" in missing[1]
    assert len(demo.missing_inputs(cfg, models=False)) == 1  # the smoke test needs no models
    raw = tmp_path / "data" / "raw" / "beijing"
    raw.mkdir(parents=True)
    (raw / "PRSA_Data_Aotizhongxin_x.csv").write_text("x")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "manifest.json").write_text("{}")
    assert demo.missing_inputs(cfg, models=True) == []


def test_the_live_demo_and_the_smoke_test_stop_early_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRQ_HOME", str(tmp_path))
    cfg = load_config()
    with pytest.raises(RuntimeError, match="download_data"):
        demo.smoke(
            cfg
        )  # before: the fleet died silently and the test reported "stations never appeared"

    class Args:
        offline = False
        no_predictor = False

    with pytest.raises(SystemExit) as exc:
        demo.run_demo(cfg, Args())
    assert "fetch_release --only demo" in str(exc.value)  # and it points at the offline alternative


def test_demo_speed_override_and_realistic_preset(capsys):
    from scripts.demo import REALISTIC_SPEEDUP, demo_speedup

    cfg = {"demo": {"speedup": 3600, "warmup_speedup": 20000}}
    assert demo_speedup(cfg, None, False) is cfg  # fast default untouched
    slow = demo_speedup(cfg, None, True)
    assert slow["demo"]["speedup"] == REALISTIC_SPEEDUP and cfg["demo"]["speedup"] == 3600
    assert demo_speedup(cfg, 120, False)["demo"]["speedup"] == 120.0
    for bad in (0, -5, 20000):  # the warm-up must stay faster than the demo
        with pytest.raises(SystemExit):
            demo_speedup(cfg, bad, False)
    with pytest.raises(SystemExit):
        demo_speedup(cfg, 120, True)
    assert "sn" in capsys.readouterr().out


def test_loop_restarts_the_demo_only_when_the_replay_ended():
    from types import SimpleNamespace

    from scripts.demo import run_loop

    codes = iter([demo.RESTART, demo.RESTART, 0])
    seen = []

    def fake_run(cfg, args):
        seen.append(args.no_browser)
        return next(codes)

    args = SimpleNamespace(no_browser=False)
    assert run_loop({}, args, run=fake_run) == 0
    assert seen == [False, True, True]  # the browser opens once; later starts reuse the tab
    # an error or a normal exit is passed through, never restarted
    assert run_loop({}, SimpleNamespace(no_browser=False), run=lambda c, a: 1) == 1


def test_the_demo_replays_to_the_end_of_the_data_and_loops_instead_of_going_offline():
    cfg = load_config()["demo"]
    assert pd.Timestamp(cfg["end"]) == pd.Timestamp("2017-02-28 23:00")  # last hour of the data
    # the loop flag exists on the command line
    out = subprocess.run(
        [sys.executable, "-m", "scripts.demo", "--help"], capture_output=True, text=True, cwd=REPO
    ).stdout
    assert "--loop" in out
