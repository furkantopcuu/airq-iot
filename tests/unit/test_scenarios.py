"""Scenario files, the command-log replay (truth), the scorecard and the player (spec 9.5-9.6)."""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from airq.devices.modes import HOUR
from airq.devices.virtual_sensor import VirtualSensor
from airq.iot.schemas import Ack, Command
from airq.scenarios.player import ScenarioPlayer
from airq.scenarios.spec import (
    Mark,
    Scenario,
    build_message,
    evaluate_expected,
    load_all,
)
from airq.server import db
from airq.server.ingest import Ingest
from airq.server.scorecard import intervention_rows, scorecard
from airq.server.truth import Truth

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "configs" / "scenarios"
T0 = pd.Timestamp("2016-06-11 00:00")


# --- scenario files --------------------------------------------------------------------------
def test_every_shipped_scenario_validates_and_matches_its_file_name():
    scenarios = load_all(SCENARIO_DIR)
    assert set(scenarios) == {
        "gercek_haze_replay", "bolgesel_artis", "yerel_artis", "sensor_takilmasi",
        "sensor_sicramasi", "cihaz_kopmasi", "ag_bozulmasi",
    }  # fmt: skip
    for sc in scenarios.values():
        assert sc.steps and sc.description
        for step in sc.steps:
            build_message(step.command)  # every step is a valid message


def test_haze_replay_starts_where_the_rq3a_window_starts():
    from airq.pipelines.rq3a import window

    reports = Path(__file__).resolve().parents[2] / "reports"
    if not (reports / "tables" / "episodes_test.csv").exists():
        pytest.skip("episode table not available")
    start, _end, onset = window({}, reports)
    sc = load_all(SCENARIO_DIR)["gercek_haze_replay"]
    assert pd.Timestamp(sc.start) == pd.Timestamp(start)
    assert pd.Timestamp(sc.start) + (sc.warmup_h + 47) * HOUR == onset  # onset 47 h after zero


def spec(**kw):
    base = {
        "name": "t", "description": "d", "duration_h": 10,
        "steps": [{"at_h": 0, "command": {"target": "A", "mode": "manual", "params": {"value": 5},
                                          "label": "x"}}],
    }  # fmt: skip
    return {**base, **kw}


def test_invalid_scenarios_are_rejected_with_a_reason():
    Scenario.model_validate(spec())
    dup = spec(steps=[spec()["steps"][0]] * 2)
    with pytest.raises(ValueError, match="duplicate label"):
        Scenario.model_validate(dup)
    with pytest.raises(ValueError, match="unknown label"):
        Scenario.model_validate(spec(expected=[{"label": "nope", "metric": "warned",
                                                "relation": "true"}]))  # fmt: skip
    with pytest.raises(ValueError, match="unknown metric"):
        Scenario.model_validate(spec(expected=[{"label": "x", "metric": "bogus",
                                                "relation": "true"}]))  # fmt: skip
    with pytest.raises(ValueError, match="exactly one of ref / value"):
        Scenario.model_validate(spec(expected=[{"label": "x", "metric": "warned",
                                                "relation": "greater_than"}]))  # fmt: skip
    late = spec(steps=[{"at_h": 11, "command": {"kind": "mark", "label": "m"}}])
    with pytest.raises(ValueError, match="after duration_h"):
        Scenario.model_validate(late)
    with pytest.raises(ValueError, match="invalid device command"):
        Scenario.model_validate(spec(steps=[{"at_h": 0, "command": {"target": "A", "mode": "x"}}]))
    with pytest.raises(ValueError):
        build_message({"kind": "teleport"})


def test_yaml_booleans_for_on_off_and_true_false_are_understood():
    sc = yaml.safe_load(
        "name: t\ndescription: d\nduration_h: 5\nsteps:\n"
        "  - {at_h: 0, command: {kind: edge, filter: off}}\n"
        "  - {at_h: 0, command: {kind: mark, label: m}}\n"
        "expected:\n  - {label: m, metric: warned, relation: true}\n"
    )
    parsed = Scenario.model_validate(sc)
    assert build_message(parsed.steps[0].command).filter == "off"
    assert parsed.expected[0].relation == "true"


def test_hypotheses_are_judged_not_edited():
    sc = Scenario.model_validate(
        spec(
            steps=[
                {"at_h": 0, "command": {"kind": "mark", "label": "a"}},
                {"at_h": 0, "command": {"kind": "mark", "label": "b"}},
            ],
            expected=[
                {"label": "a", "metric": "mae_next_6h_h6", "relation": "greater_than", "ref": "b"},
                {"label": "a", "metric": "warned", "relation": "true"},
                {"label": "b", "metric": "warned", "relation": "false"},
                {"label": "a", "metric": "lead_time_h", "relation": "greater_than", "value": 0},
            ],
        )
    )
    scores = {"a": {"mae_next_6h_h6": 5.0, "warned": False, "lead_time_h": None},
              "b": {"mae_next_6h_h6": 9.0, "warned": True}}  # fmt: skip
    got = [e["verdict"] for e in evaluate_expected(sc, scores)]
    assert got == ["refuted", "refuted", "refuted", "undetermined"]  # nothing bent to fit
    scores["a"].update(mae_next_6h_h6=12.0, warned=True, lead_time_h=3.0)
    scores["b"]["warned"] = False
    assert [e["verdict"] for e in evaluate_expected(sc, scores)] == ["confirmed"] * 4


# --- replay of the command log == what the devices emit --------------------------------------
def raw_frame(stations=("A", "B"), hours=80):
    ts = pd.date_range(T0 - 30 * HOUR, periods=hours, freq="h")
    frames = []
    for i, s in enumerate(stations):
        rng = np.random.default_rng(i)
        d = pd.DataFrame({"station": s, "ts": ts, "pm25": 60 + rng.normal(0, 10, hours),
                          "pm10": 90 + rng.normal(0, 10, hours)})  # fmt: skip
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


CAL = {"ratio": 1.4, "sigma": {"A": {"pm25": 9.0}, "B": {"pm25": 9.0}}}


class FakeClient:
    def publish(self, *a, **k):
        return self

    def wait_for_publish(self, timeout=None):
        return True


def cmd(**kw):
    base = dict(cmd_id=kw.pop("cmd_id", "c"), issued_at=datetime.now(), target="A",
                variables=["pm25"], mode="manual", params={"value": 100})  # fmt: skip
    return Command(**{**base, **kw})


def drive_devices(raw, plan):
    """Tick real VirtualSensors; `plan` = {tick_index: [Command, ...]}. Returns emitted pm25 and
    the SQLite log the ingest service would have written."""
    sensors = {
        s: VirtualSensor(s, raw[raw["station"] == s], "x", 1, coupled_ratio=CAL["ratio"],
                         sigma=CAL["sigma"][s])
        for s in ("A", "B")
    }  # fmt: skip
    for s in sensors.values():
        s.client = FakeClient()
    emitted = {s: {} for s in sensors}
    return sensors, emitted


def test_replaying_the_log_reproduces_the_device_output_exactly(tmp_path):
    raw = raw_frame()
    ts_all = list(pd.date_range(T0 - 30 * HOUR, periods=80, freq="h"))
    plan = {
        32: [cmd(cmd_id="c1", target="all", mode="ramp", params={"delta": 80}, duration_h=5,
                 coupled=True, label="ramp")],
        36: [cmd(cmd_id="c2", target="A", mode="perturb", params={"type": "stuck"}, duration_h=6)],
        40: [cmd(cmd_id="c3", target="B", mode="offline", params={}, duration_h=3)],
        48: [cmd(cmd_id="c4", target="A", mode="perturb", params={"type": "spike", "severity": 8},
                 duration_h=2)],
        52: [cmd(cmd_id="c5", target="B", mode="scale", params={"factor": 1.5}, duration_h=4)],
        60: [cmd(cmd_id="c6", target="A", mode="manual", params={"value": 300}, duration_h=3)],
        64: [cmd(cmd_id="c7", target="A", mode="replay", params={})],
    }  # fmt: skip
    sensors, emitted = drive_devices(raw, plan)
    ing = Ingest(tmp_path / "t.db")
    con = db.connect(tmp_path / "t.db")
    for i, ts in enumerate(ts_all):
        for s, sensor in sensors.items():
            msg = sensor.tick(ts)
            emitted[s][ts] = np.nan if msg is None else (np.nan if msg.pm25 is None else msg.pm25)
        for c in plan.get(i, []):  # the command arrives after tick i and applies from tick i+1
            ing._write_command(con, c.to_json().encode())
            for sensor in sensors.values():
                ack = sensor.handle_command(c.to_json())
                if ack is not None:
                    ing._write_ack(con, ack.to_json().encode())
    con.commit()
    rows = intervention_rows(con)
    truth = Truth(raw, CAL)
    for s in ("A", "B"):
        replay = truth.emitted(s, rows, ts_all[0], ts_all[-1])
        dev = pd.Series(emitted[s], dtype=float)
        common = replay.index.intersection(dev.index)
        both = pd.concat([replay[common], dev[common]], axis=1).dropna()
        assert (replay[common].isna() == dev[common].isna()).all()  # same offline hours
        assert np.allclose(both.iloc[:, 0], both.iloc[:, 1])
        recorded = raw[raw["station"] == s].set_index("ts")["pm25"].reindex(dev.index)
        assert not np.allclose(dev, recorded, equal_nan=True)  # the commands changed something
    con.close()


# --- scorecard on a hand-computed example ----------------------------------------------------
def make_db(tmp_path, with_warning=True):
    path = tmp_path / "s.db"
    con = db.connect(path)
    ing = Ingest(path)
    raw = pd.DataFrame({"station": "A", "ts": pd.date_range(T0 - 30 * HOUR, periods=100, freq="h"),
                        "pm25": 100.0, "pm10": 130.0})  # fmt: skip
    c = cmd(cmd_id="r1", target="A", mode="ramp", params={"delta": 100}, duration_h=4,
            coupled=False, label="ramp-A")  # fmt: skip
    ing._write_command(con, c.to_json().encode())
    ack = Ack(cmd_id="r1", source="A", ok=True, applied_at_ts=T0.to_pydatetime())
    ing._write_ack(con, ack.to_json().encode())
    for h in range(6):  # forecasts made during the first 6 hours: h=1 says 120, h=6 says 190
        made = T0 + h * HOUR
        for hz, yhat in ((1, 120.0), (6, 190.0)):
            db.upsert_prediction(con, {"station": "A", "made_at_ts": made.isoformat(),
                                       "target_ts": (made + hz * HOUR).isoformat(), "horizon": hz,
                                       "yhat": yhat, "n_neighbors": 7 - h})  # fmt: skip
    if with_warning:
        db.upsert_warning(con, {"station": "A", "made_at_ts": T0.isoformat(), "horizon": 6,
                                "threshold": 150.0, "yhat": 190.0, "basis": "point",
                                "sent_at": T0.isoformat()})  # fmt: skip
    for i in range(10):  # readings with seq numbers (one gap) for the delivery ratio
        t = T0 + i * HOUR
        con.execute("INSERT INTO readings(station, ts, pm25, seq, sent_at, received_at) "
                    "VALUES ('A', ?, 100, ?, '2016-06-11T00:00:00.000', '2016-06-11T00:00:00.250')",
                    (t.isoformat(), i if i < 5 else i + 1))  # fmt: skip
    con.commit()
    return con, Truth(raw, CAL)


def test_scorecard_matches_a_hand_computation(tmp_path):
    con, truth = make_db(tmp_path)
    (row,) = scorecard(con, truth)
    # emitted truth: 125, 150, 175, 200, 200 ... (ramp +100 over 4 h, then held)
    # h=1 forecasts made at t0..t0+5 target t0+1..t0+6 -> truth 150,175,200,200,200,200 vs 120
    assert row["mae_next_6h_h1"] == pytest.approx(np.mean([30, 55, 80, 80, 80, 80]))
    # h=6 targets t0+6..t0+11 are all 200 -> |190 - 200| = 10
    assert row["mae_next_6h_h6"] == pytest.approx(10.0)
    assert (row["warned"], row["matched"]) == (True, True)
    assert row["lead_time_h"] == pytest.approx(1.0)  # onset (150) at t0+1 h, warning made at t0
    assert row["peak_forecast_h6"] == 190.0 and row["min_n_neighbors"] == 2.0
    assert row["delivery_ratio"] == pytest.approx(10 / 11)  # seq 0..10 sent, 10 arrived
    assert row["latency_p95_ms"] == pytest.approx(250.0)
    assert row["edge_filter"] == "on" and row["kind"] == "world" and row["label"] == "ramp-A"
    con.close()


def test_no_warning_means_not_warned_and_not_matched(tmp_path):
    con, truth = make_db(tmp_path, with_warning=False)
    (row,) = scorecard(con, truth)
    assert (row["warned"], row["matched"], row["lead_time_h"]) == (False, False, None)
    con.close()


def test_fault_items_are_judged_against_the_clean_recording(tmp_path):
    path = tmp_path / "f.db"
    con = db.connect(path)
    ing = Ingest(path)
    raw = pd.DataFrame({"station": "A", "ts": pd.date_range(T0 - 30 * HOUR, periods=100, freq="h"),
                        "pm25": 50.0, "pm10": 70.0})  # fmt: skip
    c = cmd(cmd_id="s1", mode="perturb", params={"type": "spike", "severity": 8}, duration_h=3,
            label="spike")  # fmt: skip
    ing._write_command(con, c.to_json().encode())
    ing._write_ack(con, Ack(cmd_id="s1", source="A", ok=True,
                            applied_at_ts=T0.to_pydatetime()).to_json().encode())  # fmt: skip
    db.upsert_prediction(con, {"station": "A", "made_at_ts": T0.isoformat(), "horizon": 1,
                               "target_ts": (T0 + HOUR).isoformat(), "yhat": 200.0,
                               "n_neighbors": 11})  # fmt: skip
    db.upsert_warning(con, {"station": "A", "made_at_ts": T0.isoformat(), "horizon": 1,
                            "threshold": 150.0, "yhat": 200.0, "basis": "point",
                            "sent_at": T0.isoformat()})  # fmt: skip
    con.commit()
    (row,) = scorecard(con, Truth(raw, CAL))
    assert row["kind"] == "fault"
    assert row["mae_next_6h_h1"] == pytest.approx(150.0)  # |200 - clean 50|, not vs the spike
    assert row["warned"] is True and row["matched"] is False  # a false alarm: clean never hit 150
    con.close()


def test_marks_window_a_scorecard_row_and_remember_the_edge_state(tmp_path):
    con, truth = make_db(tmp_path)
    marks = [{"label": "w", "target": "A", "t0": T0, "duration_h": 12, "edge_filter": "off"}]
    rows = scorecard(con, truth, marks)
    mark = next(r for r in rows if r["label"] == "w")
    assert mark["kind"] == "mark" and mark["edge_filter"] == "off"
    assert pd.Timestamp(mark["t1"]) - pd.Timestamp(mark["t0"]) == 12 * HOUR
    con.close()


# --- player -----------------------------------------------------------------------------------
class FakeController:
    def __init__(self, fail_ids=()):
        self.sent, self.fail_ids = [], set(fail_ids)

    def send(self, msg):
        self.sent.append(msg)

    def wait_acks(self, cmd_id, expect=1, timeout_s=5.0):
        ok = cmd_id not in self.fail_ids
        return [Ack(cmd_id=cmd_id, source=f"s{i}", ok=ok, error=None if ok else "no")
                for i in range(expect)]  # fmt: skip


def test_player_fires_each_step_once_at_its_simulated_time():
    sc = Scenario.model_validate(
        spec(
            duration_h=30,
            steps=[
                {"at_h": 0, "command": {"kind": "edge", "filter": "off"}},
                {"at_h": 0, "command": {"kind": "mark", "label": "m", "duration_h": 5}},
                {
                    "at_h": 2,
                    "command": {
                        "target": "all",
                        "mode": "scale",
                        "params": {"factor": 2},
                        "duration_h": 3,
                        "label": "all-x2",
                    },
                },
                {"at_h": 14, "command": {"kind": "edge", "filter": "on"}},
            ],
        )
    )
    ctl = FakeController()
    player = ScenarioPlayer(sc, ctl, ["A", "B", "C"], zero_ts=T0)
    assert len(player.tick(T0)) == 2 and len(ctl.sent) == 1  # edge off sent, mark recorded
    assert player.tick(T0 + 1 * HOUR) == []
    fired = player.tick(T0 + 2 * HOUR)
    assert [e["label"] for e in fired] == ["all-x2"] and fired[0]["ok"]
    assert player.tick(T0 + 2 * HOUR) == []  # never twice
    assert not player.done
    player.tick(T0 + 20 * HOUR)  # a jump past the step still fires it
    assert player.done and [type(m).__name__ for m in ctl.sent] == [
        "EdgeControl",
        "Command",
        "EdgeControl",
    ]
    mark = player.marks[0]
    assert mark["label"] == "m" and mark["t0"] == T0 and mark["edge_filter"] == "off"
    assert player.status()["steps_fired"] == 4


def test_player_reports_missing_and_negative_acks():
    sc = Scenario.model_validate(spec(duration_h=5))
    ctl = FakeController(fail_ids=set())
    player = ScenarioPlayer(sc, ctl, ["A"], zero_ts=T0)

    class Failing(FakeController):
        def wait_acks(self, cmd_id, expect=1, timeout_s=5.0):
            return []

    player.controller = Failing()
    (entry,) = player.tick(T0)
    assert entry["ok"] is False and "only 0 of 1 acks" in entry["errors"][0]


def test_mark_is_a_value_object():
    assert Mark("x").target == "all" and json.dumps({"a": Mark("x").label})


# --- onset logic (scoring version 2) ---------------------------------------------------------
def series(values, start="2016-06-11 00:00"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="h"), dtype=float)


def test_a_window_that_opens_inside_a_haze_has_no_onset_until_it_clears():
    from airq.server.scorecard import episode_end, first_onset, onsets

    lo = pd.Timestamp("2016-06-11 00:00")
    running = series([200] * 8 + [50] * 8 + [200] * 4)  # haze already on at t0, clears, returns
    t0 = lo + 6 * HOUR  # context hours 0..5 are already above 150
    assert onsets(running, t0) == [lo + 16 * HOUR]  # only the second wave is an onset
    assert first_onset(running, t0) == lo + 16 * HOUR
    assert episode_end(running, lo + 16 * HOUR) == lo + 19 * HOUR
    calm = series([50] * 8 + [300] * 3 + [50] * 3)
    assert onsets(calm, lo + 6 * HOUR) == [lo + 8 * HOUR]  # a front out of clean air is an onset


def test_short_dips_do_not_split_an_episode_and_unknown_history_is_not_an_onset():
    from airq.server.scorecard import onsets

    lo = pd.Timestamp("2016-06-11 00:00")
    dip = series([50] * 6 + [200, 200, 100, 100, 200, 200] + [50] * 8)  # 2 h dip < 6 h gap
    assert onsets(dip, lo + 6 * HOUR) == [lo + 6 * HOUR]  # one episode, one onset
    assert onsets(series([200] * 3 + [50] * 8), lo) == []  # no 6 h of history before the start
    nan_ok = series([50, np.nan, 50, 50, 50, 50] + [200] * 3)
    assert onsets(nan_ok, lo + 6 * HOUR) == [lo + 6 * HOUR]  # missing hours count as "below"


def test_a_warning_for_an_earlier_episode_does_not_give_a_lead_time(tmp_path):
    """Version 1 accepted any matching warning; a 24 h warning for the running haze must not
    count for the next, separate onset."""
    path = tmp_path / "e.db"
    con = db.connect(path)
    ts = pd.date_range(T0 - 30 * HOUR, periods=120, freq="h")
    vals = np.where((ts >= T0 + 10 * HOUR) & (ts < T0 + 14 * HOUR), 200.0, 50.0)
    vals = np.where((ts >= T0 + 40 * HOUR) & (ts < T0 + 44 * HOUR), 200.0, vals)
    raw = pd.DataFrame({"station": "A", "ts": ts, "pm25": vals, "pm10": vals * 1.3})
    for made_h, hz in ((8, 3), (30, 6)):  # good for episode 1 (target T0+11); target T0+36 is calm
        db.upsert_warning(con, {"station": "A", "made_at_ts": (T0 + made_h * HOUR).isoformat(),
                                "horizon": hz, "threshold": 150.0, "yhat": 190.0,
                                "basis": "point", "sent_at": ""})  # fmt: skip
    db.upsert_warning(con, {"station": "A", "made_at_ts": (T0 + 41 * HOUR).isoformat(),
                            "horizon": 1, "threshold": 150.0, "yhat": 190.0, "basis": "point",
                            "sent_at": ""})  # fmt: skip
    con.commit()
    from airq.server.scorecard import Item, score_item

    item = Item("w", ["A"], T0, T0 + 60 * HOUR, "mark", "mark")
    row = score_item(con, item, [], Truth(raw, CAL))
    assert row["n_onsets"] == 2
    assert row["n_onsets_warned_ahead"] == 1  # episode 1 caught 2 h ahead (made T0+8, onset T0+10)
    assert row["lead_time_h"] == pytest.approx(
        2.0
    )  # the T0+41 warning is one hour after episode 2 began
    con.close()


# --- paired A/B scenarios ---------------------------------------------------------------------
def test_ab_variants_differ_only_in_the_edge_filter():
    from airq.pipelines.scenarios import AB_DURATION_H, ab_variants

    base = load_all(SCENARIO_DIR)["sensor_takilmasi"]
    v = ab_variants(base, "2016-07-20 00:00")
    assert set(v) == {"off", "on"} and v["off"].name == "ab_sensor_takilmasi_20160720_off"
    off_steps, on_steps = v["off"].steps, v["on"].steps
    assert [build_message(s.command).filter for s in (off_steps[0], on_steps[0])] == ["off", "on"]
    assert off_steps[1].command == on_steps[1].command  # the SAME fault, same time, same label
    assert off_steps[1].command["label"] == "fault" and off_steps[1].command["mode"] == "perturb"
    assert off_steps[1].at_h == on_steps[1].at_h == 0
    assert v["off"].start == v["on"].start == "2016-07-20 00:00"
    assert v["off"].duration_h == AB_DURATION_H and v["off"].warmup_h == base.warmup_h


def test_ab_table_and_paired_differences_from_stored_runs(tmp_path):
    from airq.pipelines.scenarios import paired_differences, write_ab_table

    folder = tmp_path / "scenarios" / "ab"
    folder.mkdir(parents=True)
    maes = {"off": (30.0, 20.0), "on": (10.0, 12.0)}
    for state, (h1, h6) in maes.items():
        run = {
            "scenario": f"ab_sensor_sicramasi_20161005_{state}",
            "sim_start": "2016-10-05 00:00:00",
            "scorecard": [
                {"label": "fault", "warned": state == "off", "matched": False,
                 "mae_window_h1": h1, "mae_window_h6": h6, "mae_next_6h_h1": h1,
                 "mae_next_6h_h6": h6, "peak_forecast_h6": 90.0 if state == "off" else 50.0,
                 "n_forecasts": 12}
            ],
        }  # fmt: skip
        (folder / f"{run['scenario']}.json").write_text(json.dumps(run))
    path = write_ab_table(tmp_path)
    df = pd.read_csv(path)
    assert sorted(df["edge"]) == ["off", "on"] and set(df["fault"]) == {"sensor_sicramasi"}
    assert set(df["start"]) == {"2016-10-05"}
    d = paired_differences(df).iloc[0]
    assert d["mae_window_h1_diff"] == 20.0 and d["mae_window_h6_diff"] == 8.0
    assert d["peak_forecast_h6_diff"] == 40.0  # positive = the filter helped
