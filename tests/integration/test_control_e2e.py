"""Senaryo Kontrol command channel over a real broker (marker `broker`): cmd -> device -> ack."""

import json
import threading
import time
import uuid
from datetime import datetime

import pandas as pd
import pytest
from paho.mqtt.client import topic_matches_sub

from airq.devices.fleet import run_fleet
from airq.edge.gateway import run as run_edge
from airq.edge.quality import QualityParams
from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import Command, EdgeControl, FleetControl, NetControl, Telemetry
from airq.server import db
from airq.server.control import Controller
from airq.server.ingest import Ingest

pytestmark = pytest.mark.broker

STATIONS = ["Dongsi", "Huairou"]


def _wait(cond, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _raw(hours=40):
    ts = pd.date_range("2016-03-01", periods=hours, freq="h")
    frames = []
    for s in STATIONS:
        d = pd.DataFrame({"station": s, "ts": ts, "pm25": 100.0, "pm10": 130.0})
        for c in ["so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]:
            d[c] = 1.0
        d["wd"] = "N"
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def _id():
    return str(uuid.uuid4())


def _now():
    return datetime.now()


def _cmd(**kw):
    base = dict(cmd_id=_id(), issued_at=_now(), target="Dongsi", mode="manual",
                variables=["pm25"], params={"value": 300}, duration_h=3)  # fmt: skip
    return Command(**{**base, **kw})


class Fleet:
    """run_fleet with control=True in a background thread (1 simulated hour = 0.5 s)."""

    def __init__(self, broker, hours=40, speedup=7200):
        self.stop = threading.Event()
        self.out = {}
        end = str(pd.Timestamp("2016-03-01") + pd.Timedelta(hours=hours - 1))
        cal = {"ratio": 1.3, "sigma": {"Dongsi": {"pm25": 10.0}}}

        def target():
            self.out.update(
                run_fleet(
                    _raw(hours), STATIONS, "2016-03-01 00:00", end, *broker,
                    speedup=speedup, stop=self.stop, control=True, calibration=cal,
                )
            )  # fmt: skip

        self.thread = threading.Thread(target=target, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=20)


def _collect(broker, filters, cid):
    got = []
    client = make_client(cid)

    def on_message(
        _c, _u, m
    ):  # drop amqtt's loosely matched retained messages (see test_mqtt_devices)
        if any(topic_matches_sub(f, m.topic) for f in filters):
            got.append((m.topic, m.payload))

    client.on_message = on_message
    connect_blocking(client, *broker)
    for f in filters:
        client.subscribe(f, qos=1)
    time.sleep(0.3)
    return client, got


def _tele(got, station):
    return [Telemetry.from_json(p) for t, p in got if t == f"airq/raw/{station}/telemetry"]


def test_device_command_changes_telemetry_then_returns_to_replay(broker):
    sub, got = _collect(broker, [topics.RAW_ALL], "ctl-watch-1")
    ctl = Controller(*broker, client_id="ctl-1")
    ctl.start()
    with Fleet(broker):
        assert _wait(lambda: len(_tele(got, "Dongsi")) >= 2)
        cmd = _cmd(label="e2e")
        ctl.send(cmd)
        acks = ctl.wait_acks(cmd.cmd_id, 1, 5)
        assert len(acks) == 1 and acks[0].ok and acks[0].source == "Dongsi"
        assert _wait(lambda: any(m.pm25 == 300.0 for m in _tele(got, "Dongsi")))
        assert _wait(
            lambda: _tele(got, "Dongsi")[-1].pm25 == 100.0 and len(_tele(got, "Dongsi")) > 8
        )
    d = sorted(_tele(got, "Dongsi"), key=lambda m: m.seq)
    hit = [m.seq for m in d if m.pm25 == 300.0]
    assert len(hit) == 3 and hit == list(range(hit[0], hit[0] + 3))  # exactly duration_h hours
    assert all(m.pm25 == 100.0 for m in _tele(got, "Huairou"))  # the other station never changed
    ctl.stop()
    disconnect(sub)


def test_invalid_command_gets_an_error_ack_and_changes_nothing(broker):
    sub, got = _collect(broker, [topics.RAW_ALL], "ctl-watch-2")
    ctl = Controller(*broker, client_id="ctl-2")
    ctl.start()
    with Fleet(broker, hours=20):
        assert _wait(lambda: len(_tele(got, "Dongsi")) >= 1)
        cmd = _cmd(params={"value": 5000})
        ctl.send(cmd)
        ack = ctl.wait_acks(cmd.cmd_id, 1, 5)[0]
        assert not ack.ok and "physical range" in ack.error
        ok = _cmd(params={"value": 5000}, allow_invalid=True, duration_h=1)
        ctl.send(ok)
        assert ctl.wait_acks(ok.cmd_id, 1, 5)[0].ok
        assert _wait(lambda: any(m.pm25 == 5000.0 for m in _tele(got, "Dongsi")))
    assert not any(m.pm25 == 5000.0 for m in _tele(got, "Huairou"))
    ctl.stop()
    disconnect(sub)


def test_fleet_commands_pause_net_loss_and_all_target(broker):
    sub, got = _collect(broker, [topics.RAW_ALL], "ctl-watch-3")
    ctl = Controller(*broker, client_id="ctl-3")
    ctl.start()
    with Fleet(broker, hours=60):
        assert _wait(lambda: len(_tele(got, "Dongsi")) >= 2)
        pause = FleetControl(cmd_id=_id(), issued_at=_now(), action="pause")
        ctl.send(pause)
        assert ctl.wait_acks(pause.cmd_id, 1, 5)[0].ok
        time.sleep(1.0)  # let an in-flight hour finish
        n = len(_tele(got, "Dongsi"))
        time.sleep(1.5)
        assert len(_tele(got, "Dongsi")) == n  # the simulated clock stands still
        loss = NetControl(cmd_id=_id(), issued_at=_now(), target="Huairou", loss_rate=1.0)
        ctl.send(loss)
        assert ctl.wait_acks(loss.cmd_id, 1, 5)[0].source == "net"
        every = _cmd(target="all", mode="offset", params={"delta": 25}, duration_h=2)
        ctl.send(every)
        resume = FleetControl(cmd_id=_id(), issued_at=_now(), action="resume")
        ctl.send(resume)
        acks = ctl.wait_acks(every.cmd_id, 2, 5)
        assert sorted(a.source for a in acks) == STATIONS and all(a.ok for a in acks)
        assert _wait(lambda: len(_tele(got, "Dongsi")) >= n + 6)
    huairou = len(_tele(got, "Huairou"))
    dongsi = _tele(got, "Dongsi")
    assert huairou <= n + 1  # 100 % emulated loss: (almost) nothing more arrives
    assert len(dongsi) >= n + 6 and sum(m.pm25 == 125.0 for m in dongsi) == 2
    ctl.stop()
    disconnect(sub)


def test_edge_filter_command_is_acked_and_visible_in_stats(broker):
    sub, got = _collect(broker, ["airq/edge/stats"], "ctl-watch-4")
    stop = threading.Event()
    edge = threading.Thread(
        target=lambda: run_edge(QualityParams(), *broker, True, stop, stats_every_s=0.3),
        daemon=True,
    )
    edge.start()
    ctl = Controller(*broker, client_id="ctl-4")
    ctl.start()
    assert _wait(lambda: got)  # edge is up and publishing stats
    off = EdgeControl(cmd_id=_id(), issued_at=_now(), filter="off")
    ctl.send(off)
    ack = ctl.wait_acks(off.cmd_id, 1, 5)[0]
    assert ack.ok and ack.source == "edge"
    assert _wait(lambda: json.loads(got[-1][1])["filter_on"] is False)
    on = EdgeControl(cmd_id=_id(), issued_at=_now(), filter="on")
    ctl.send(on)
    assert ctl.wait_acks(on.cmd_id, 1, 5)[0].ok
    assert _wait(lambda: json.loads(got[-1][1])["filter_on"] is True)
    stop.set()
    edge.join(timeout=10)
    ctl.stop()
    disconnect(sub)


def test_ingest_writes_the_interventions_table_from_live_commands(broker, tmp_path):
    ing = Ingest(tmp_path / "live.db")
    ing.start(*broker)
    ctl = Controller(*broker, client_id="ctl-5")
    ctl.start()
    with Fleet(broker, hours=20):
        time.sleep(1.0)
        cmd = _cmd(label="demo-yerel", duration_h=2)
        ctl.send(cmd)
        ctl.wait_acks(cmd.cmd_id, 1, 5)
        bad = _cmd(params={"value": -50})
        ctl.send(bad)
        ctl.wait_acks(bad.cmd_id, 1, 5)
        every = _cmd(target="all", mode="scale", params={"factor": 1.1}, duration_h=1)
        ctl.send(every)
        ctl.wait_acks(every.cmd_id, 2, 5)
        assert _wait(
            lambda: ing.flush(2) and _rows(tmp_path).get(every.cmd_id, {}).get("acked") == 2
        )
    rows = _rows(tmp_path)
    ok, err, both = rows[cmd.cmd_id], rows[bad.cmd_id], rows[every.cmd_id]
    assert (ok["station"], ok["mode"], ok["label"], ok["acked"]) == (
        "Dongsi",
        "manual",
        "demo-yerel",
        1,
    )
    assert ok["start_ts"] is not None and ok["end_ts"] is not None  # 2 h window recorded
    assert err["acked"] == 0 and "physical range" in err["error"]
    assert both["station"] == "all" and both["acked"] == 2
    ctl.stop()
    ing.stop()


def _rows(tmp_path):
    con = db.connect(tmp_path / "live.db", read_only=True)
    try:
        return {r["cmd_id"]: dict(r) for r in con.execute("SELECT * FROM interventions")}
    finally:
        con.close()
