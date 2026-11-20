"""Command channel without a broker: schemas, device ack, fleet/net/edge control, log."""

import json

import numpy as np
import pandas as pd
import pytest

from airq.devices.fleet import FleetController, FleetState, train_calibration
from airq.devices.netem import NetEm
from airq.devices.virtual_sensor import VirtualSensor
from airq.edge.gateway import EdgeGateway
from airq.edge.quality import QualityParams
from airq.iot import topics
from airq.iot.schemas import (
    Ack,
    Command,
    EdgeControl,
    FleetControl,
    NetControl,
    parse_command,
)
from airq.server import db
from airq.server.control import topic_for
from airq.server.ingest import Ingest

ISSUED = "2016-03-01T00:00:00"


def device_cmd(**kw):
    base = {"cmd_id": "c1", "issued_at": ISSUED, "target": "Dongsi", "mode": "manual",
            "variables": ["pm25"], "params": {"value": 250}}  # fmt: skip
    return json.dumps({**base, **kw})


class FakeClient:
    """Stands in for the paho client: records what the device would publish."""

    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.sent.append((topic, payload, retain))
        return self

    def wait_for_publish(self, timeout=None):
        return True


def sensor(station="Dongsi", sigma=None):
    ts = pd.date_range("2016-03-01", periods=6, freq="h")
    df = pd.DataFrame({"station": station, "ts": ts, "pm25": 100.0, "pm10": 130.0, "wd": "N"})
    for c in ["so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]:
        df[c] = 1.0
    s = VirtualSensor(station, df, "127.0.0.1", 1, sigma=sigma, coupled_ratio=1.3)
    s.client = FakeClient()
    return s


# --- schemas and routing ---------------------------------------------------------------------
def test_parse_command_dispatches_by_message_kind():
    assert isinstance(parse_command(device_cmd()), Command)
    fleet = {"cmd_id": "f", "issued_at": ISSUED, "action": "pause"}
    assert isinstance(parse_command(json.dumps(fleet)), FleetControl)
    net = {"cmd_id": "n", "issued_at": ISSUED, "loss_rate": 0.2}
    assert isinstance(parse_command(json.dumps(net)), NetControl)
    edge = {"cmd_id": "e", "issued_at": ISSUED, "filter": "off"}
    assert isinstance(parse_command(json.dumps(edge)), EdgeControl)
    for bad in ("not json", "[1]", '{"cmd_id": "x"}'):
        with pytest.raises(ValueError):
            parse_command(bad)


def test_invalid_control_messages_are_rejected():
    with pytest.raises(ValueError):
        FleetControl(cmd_id="f", issued_at=ISSUED, action="speedup", value=-1)
    with pytest.raises(ValueError):
        FleetControl(cmd_id="f", issued_at=ISSUED, action="jump", value="yesterday")
    with pytest.raises(ValueError):
        NetControl(cmd_id="n", issued_at=ISSUED, loss_rate=1.5)
    with pytest.raises(ValueError):
        EdgeControl(cmd_id="e", issued_at=ISSUED, filter="maybe")


def test_topic_routing_matches_the_topic_table():
    cmd = Command.from_json(device_cmd())
    assert topic_for(cmd) == "airq/cmd/Dongsi"
    assert topic_for(Command.from_json(device_cmd(target="all"))) == "airq/cmd/fleet"
    assert topic_for(FleetControl(cmd_id="f", issued_at=ISSUED, action="pause")) == "airq/cmd/fleet"
    assert topic_for(NetControl(cmd_id="n", issued_at=ISSUED)) == "airq/cmd/net"
    assert topic_for(EdgeControl(cmd_id="e", issued_at=ISSUED, filter="on")) == "airq/cmd/edge"
    assert topics.topic(topics.CMD_ACK, "edge") == "airq/cmd/ack/edge"
    assert topics.CMD_STATION.qos == topics.CMD_ACK.qos == 1 and not topics.CMD_ACK.retained


# --- device ----------------------------------------------------------------------------------
def test_device_acks_a_valid_command_and_the_next_reading_is_intervened():
    s = sensor()
    s.current_ts = pd.Timestamp("2016-03-01 01:00")
    ack = s.handle_command(device_cmd(params={"value": 250}))
    assert ack.ok and ack.error is None and ack.source == "Dongsi" and ack.cmd_id == "c1"
    assert ack.applied_at_ts == pd.Timestamp("2016-03-01 02:00").to_pydatetime()  # next tick
    msg = s.tick(pd.Timestamp("2016-03-01 02:00"))
    assert msg.pm25 == 250.0 and msg.pm10 == 130.0
    s.handle_command(device_cmd(cmd_id="c2", mode="replay", params={}))
    assert s.tick(pd.Timestamp("2016-03-01 03:00")).pm25 == 100.0


def test_device_acks_an_error_for_invalid_commands_and_ignores_foreign_ones():
    s = sensor()
    bad = s.handle_command(device_cmd(cmd_id="b1", params={"value": 5000}))
    assert not bad.ok and "physical range" in bad.error and bad.applied_at_ts is None
    assert s.iv.count() == 0  # nothing applied
    ok = s.handle_command(device_cmd(cmd_id="b2", params={"value": 5000}, allow_invalid=True))
    assert ok.ok  # the faulty-input checkbox lets it through
    broken = s.handle_command(device_cmd(cmd_id="b3", mode="ramp", params={}))
    assert not broken.ok and broken.cmd_id == "b3"  # malformed but answerable
    assert s.handle_command("garbage") is None  # cannot be answered
    assert s.handle_command(device_cmd(target="Huairou")) is None  # another station
    assert (
        s.handle_command(json.dumps({"cmd_id": "f", "issued_at": ISSUED, "action": "pause"}))
        is None
    )
    assert s.handle_command(device_cmd(target="all", cmd_id="all1")).ok  # fleet-wide counts


def test_offline_command_announces_offline_publishes_nothing_and_returns():
    s = sensor()
    s.handle_command(device_cmd(mode="offline", params={}, duration_h=2, variables=["pm25"]))
    ticks = [s.tick(pd.Timestamp("2016-03-01 00:00") + pd.Timedelta(hours=h)) for h in range(4)]
    assert [t is None for t in ticks] == [True, True, False, False]
    assert ticks[2].seq == 0  # silent hours consumed no seq: the edge sees no loss, just silence


def test_spike_uses_the_train_sigma_given_to_the_device():
    s = sensor(sigma={"pm25": 8.0})
    s.handle_command(device_cmd(mode="perturb", params={"type": "spike", "severity": 5},
                                duration_h=1))  # fmt: skip
    assert s.tick(pd.Timestamp("2016-03-01 00:00")).pm25 == 140.0
    assert s.tick(pd.Timestamp("2016-03-01 01:00")).pm25 == 100.0


# --- fleet / net -----------------------------------------------------------------------------
def fleet_controller():
    sensors = [sensor("Dongsi"), sensor("Huairou")]
    return FleetController(FleetState(3600), sensors, NetEm()), sensors


def msg(**kw):
    return json.dumps({"cmd_id": "x", "issued_at": ISSUED, **kw})


def test_fleet_pause_resume_speedup_jump_reset():
    ctl, sensors = fleet_controller()
    st = ctl.state
    assert ctl.handle(msg(action="pause"))[1].ok and not st.running.is_set()
    assert ctl.handle(msg(action="resume"))[1].ok and st.running.is_set()
    assert ctl.handle(msg(action="speedup", value=7200))[1].ok
    assert st.speedup == 7200 and st.per_hour_s() == 0.5
    ctl.handle(msg(action="jump", value="2016-12-01 00:00"))
    assert st.jump_to == pd.Timestamp("2016-12-01")
    sensors[0].handle_command(device_cmd(params={"value": 250}))
    ctl.netem.set(__import__("airq.devices.netem", fromlist=["NetParams"]).NetParams(loss_rate=0.5))
    source, ack = ctl.handle(msg(action="reset"))
    assert source == "fleet" and ack.ok
    assert sensors[0].iv.count() == 0 and ctl.netem.plan("Dongsi") == 0.0


def test_net_command_sets_fleet_wide_and_per_station_emulation():
    ctl, _ = fleet_controller()
    source, ack = ctl.handle(msg(loss_rate=1.0, target="Huairou"))
    assert source == "net" and ack.ok
    assert ctl.netem.plan("Huairou") is None and ctl.netem.plan("Dongsi") == 0.0
    ctl.handle(msg(delay_ms=300))  # all stations
    assert ctl.netem.plan("Dongsi") == 0.3 and ctl.netem.plan("Huairou") is None  # override wins
    assert ctl.handle(msg(loss_rate=0.1, target="Nowhere"))[1].ok is False
    assert ctl.handle(msg(reset=True, target="Huairou"))[1].ok
    assert ctl.netem.plan("Huairou") == 0.3
    ctl.handle(msg(reset=True))
    assert ctl.netem.plan("Dongsi") == 0.0


def test_fleet_controller_ignores_device_and_edge_messages_and_garbage():
    ctl, _ = fleet_controller()
    assert ctl.handle(device_cmd()) is None
    assert ctl.handle(msg(filter="off")) is None
    assert ctl.handle("garbage") is None


# --- edge ------------------------------------------------------------------------------------
def test_edge_filter_can_be_switched_by_command():
    gw = EdgeGateway(QualityParams(), filter_on=True)
    ack = gw.handle_control(msg(filter="off"))
    assert ack.ok and ack.source == "edge" and not gw.filter_on and gw.stats()["filter_on"] is False
    gw.handle_control(msg(filter="on"))
    assert gw.filter_on
    assert gw.handle_control(device_cmd()) is None and gw.handle_control("garbage") is None


# --- calibration (no leakage) ----------------------------------------------------------------
def test_train_calibration_uses_train_rows_only():
    ts = pd.date_range("2015-08-31 00:00", periods=48, freq="h")  # crosses the train end
    pm25 = np.where(ts <= pd.Timestamp("2015-08-31 23:00"), 100.0, 900.0)
    pm10 = np.where(ts <= pd.Timestamp("2015-08-31 23:00"), 150.0, 9.0)
    raw = pd.DataFrame({"station": "A", "ts": ts, "pm25": pm25, "pm10": pm10})
    cfg = {"split": {"train": ["2013-03-01 00:00", "2015-08-31 23:00"]}}
    cal = train_calibration(raw, cfg)
    assert cal["ratio"] == pytest.approx(1.5)  # the later (test-like) rows are ignored
    assert cal["sigma"]["A"]["pm25"] == 0.0  # constant on train


# --- interventions log (ingest is the single writer) -----------------------------------------
def test_ingest_logs_commands_and_acks_in_interventions(tmp_path):
    ing = Ingest(tmp_path / "t.db")
    con = db.connect(tmp_path / "t.db")
    ack = lambda ok=True, error=None, ts="2016-03-01T05:00:00", cid="c1": Ack(  # noqa: E731
        cmd_id=cid, source="Dongsi", ok=ok, error=error, applied_at_ts=ts
    ).to_json()
    ing._write_ack(con, ack().encode())  # the ack may arrive BEFORE the command row
    ing._write_command(con, device_cmd(duration_h=6, label="demo").encode())
    ing._write_command(con, device_cmd(duration_h=6, label="demo").encode())  # QoS 1 duplicate
    row = con.execute("SELECT * FROM interventions WHERE cmd_id='c1'").fetchone()
    assert (row["station"], row["mode"], row["label"]) == ("Dongsi", "manual", "demo")
    assert json.loads(row["params"])["value"] == 250 and row["acked"] == 1
    assert row["start_ts"] == "2016-03-01T05:00:00"
    ing._write_ack(con, ack().encode())  # re-ack must not move start/end
    row = con.execute("SELECT * FROM interventions WHERE cmd_id='c1'").fetchone()
    assert row["end_ts"] == "2016-03-01T11:00:00"  # start + 6 h

    ing._write_command(con, device_cmd(cmd_id="c2", mode="ramp", params={"target": 200},
                                       duration_h=4).encode())  # fmt: skip
    ing._write_ack(con, ack(cid="c2").encode())
    assert con.execute("SELECT end_ts FROM interventions WHERE cmd_id='c2'").fetchone()[0] is None
    ing._write_command(con, device_cmd(cmd_id="c3", params={"value": 9999}).encode())
    ing._write_ack(con, ack(False, "outside the physical range", None, "c3").encode())
    row = con.execute("SELECT * FROM interventions WHERE cmd_id='c3'").fetchone()
    assert row["acked"] == 0 and "physical range" in row["error"]

    ing._write_command(con, msg(cmd_id="f1", action="speedup", value=7200).encode())
    ing._write_command(con, msg(cmd_id="n1", loss_rate=0.2, target="all").encode())
    ing._write_command(con, msg(cmd_id="e1", filter="off").encode())
    rows = {r["cmd_id"]: r for r in con.execute("SELECT * FROM interventions")}
    assert (rows["f1"]["station"], rows["f1"]["mode"]) == ("fleet", "speedup")
    assert (rows["n1"]["mode"], json.loads(rows["n1"]["params"])["loss_rate"]) == ("net", 0.2)
    assert (rows["e1"]["station"], rows["e1"]["mode"]) == ("edge", "filter")
    ing._write_command(con, b"garbage")  # ignored, no exception
    ing._write_ack(con, b"garbage")
    con.close()
