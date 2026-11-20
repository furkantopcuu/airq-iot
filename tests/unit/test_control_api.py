"""POST/GET /control/* with an injected fake controller (no broker), plus the log fold."""

import json
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from airq.iot.schemas import Ack
from airq.server import db
from airq.server.api import create_app
from airq.server.control_api import active_state
from airq.server.truth import Truth

SCENARIOS = __import__("pathlib").Path(__file__).resolve().parents[2] / "configs" / "scenarios"
T0 = pd.Timestamp("2016-06-11 00:00")


class FakeController:
    """mode: ok (expect acks) | none (silence) | reject (one error ack) | partial (one ok ack)."""

    def __init__(self, mode="ok"):
        self.mode, self.sent = mode, []

    def send(self, msg):
        self.sent.append(msg)

    def wait_acks(self, cmd_id, expect=1, timeout_s=5.0):
        if self.mode == "none":
            return []
        if self.mode == "reject":
            return [
                Ack(cmd_id=cmd_id, source="Dongsi", ok=False, error="outside the physical range")
            ]
        n = 1 if self.mode == "partial" else expect
        return [Ack(cmd_id=cmd_id, source=f"s{i}", ok=True, applied_at_ts=T0.to_pydatetime())
                for i in range(n)]  # fmt: skip


@pytest.fixture
def stack(tmp_path):
    path = tmp_path / "c.db"
    con = db.connect(path)
    for st in ("Dongsi", "Huairou", "Gucheng"):
        db.set_device_status(con, st, "online", "2016-06-11T00:00:00")
    con.execute("INSERT INTO readings(station, ts, pm25, seq) VALUES ('Dongsi', ?, 50, 1)",
                (T0.isoformat(),))  # fmt: skip
    con.commit()
    con.close()

    def make(mode="ok", truth=None):
        ctl = FakeController(mode)
        app = create_app(path, tmp_path, controller=ctl, truth=truth, scenarios_dir=SCENARIOS)
        return TestClient(app), ctl

    return make


DEVICE = {"target": "Dongsi", "variables": ["pm25"], "mode": "manual", "params": {"value": 250},
          "duration_h": 3, "label": "demo"}  # fmt: skip


def test_device_command_is_validated_sent_and_answered(stack):
    client, ctl = stack()
    r = client.post("/control/device", json=DEVICE)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["errors"] == [] and len(body["acks"]) == 1
    sent = ctl.sent[0]
    assert (sent.target, sent.mode, sent.params, sent.label) == (
        "Dongsi",
        "manual",
        {"value": 250},
        "demo",
    )
    assert body["cmd_id"] == sent.cmd_id and len(sent.cmd_id) == 36  # a uuid, server-made


def test_invalid_commands_are_rejected_with_422_and_never_sent(stack):
    client, ctl = stack()
    bad = [
        ("/control/device", {**DEVICE, "mode": "ramp", "params": {}}),
        ("/control/device", {**DEVICE, "variables": ["pm99"]}),
        ("/control/device", {**DEVICE, "cmd_id": "mine"}),  # ids are made by the server
        ("/control/fleet", {"action": "speedup", "value": -5}),
        ("/control/fleet", {"action": "explode"}),
        ("/control/network", {"loss_rate": 1.5}),
        ("/control/edge", {"filter": "maybe"}),
    ]
    for url, body in bad:
        assert client.post(url, json=body).status_code == 422, (url, body)
    assert ctl.sent == []


def test_a_device_that_refuses_is_reported_not_hidden(stack):
    client, _ = stack("reject")
    r = client.post("/control/device", json={**DEVICE, "params": {"value": 5000}})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "physical range" in r.json()["errors"][0]


def test_silence_is_a_gateway_timeout(stack):
    client, _ = stack("none")
    r = client.post("/control/device", json=DEVICE)
    assert r.status_code == 504 and "no ack" in r.json()["detail"]


def test_all_target_waits_for_every_online_device(stack):
    client, _ = stack("ok")
    r = client.post("/control/device", json={**DEVICE, "target": "all"})
    assert len(r.json()["acks"]) == 3 and r.json()["ok"]  # 3 devices online in the fixture
    client, _ = stack("partial")
    r = client.post("/control/device", json={**DEVICE, "target": "all"})
    assert r.json()["ok"] is False and "only 1 of 3 devices answered" in r.json()["errors"][0]


def test_fleet_network_and_edge_commands(stack):
    client, ctl = stack()
    for url, body in [
        ("/control/fleet", {"action": "pause"}),
        ("/control/fleet", {"action": "speedup", "value": 7200}),
        ("/control/network", {"target": "Dongsi", "loss_rate": 0.2, "delay_ms": 300}),
        ("/control/edge", {"filter": "off"}),
    ]:
        r = client.post(url, json=body)
        assert r.status_code == 200 and r.json()["ok"], url
    assert [type(m).__name__ for m in ctl.sent] == [
        "FleetControl",
        "FleetControl",
        "NetControl",
        "EdgeControl",
    ]


def test_reset_clears_everything_and_switches_the_filter_on(stack):
    client, ctl = stack()
    r = client.post("/control/reset")
    assert r.status_code == 200 and r.json()["ok"]
    kinds = [
        (type(m).__name__, getattr(m, "action", None) or getattr(m, "filter", None))
        for m in ctl.sent
    ]
    assert kinds == [("FleetControl", "reset"), ("EdgeControl", "on")]


def test_scenarios_are_listed_and_run_in_simulated_time(stack):
    client, ctl = stack()
    names = {s["name"] for s in client.get("/control/scenarios").json()}
    assert "sensor_takilmasi" in names and len(names) == 7
    assert client.post("/control/scenario/nope").status_code == 404
    r = client.post("/control/scenario/sensor_takilmasi")
    assert r.status_code == 200 and r.json()["name"] == "sensor_takilmasi"
    assert r.json()["zero_ts"] == T0.isoformat()  # time zero = the newest simulated reading
    for _ in range(100):  # steps at_h=0 fire at once, the at_h=14 ones wait for the clock
        if len(ctl.sent) >= 2:
            break
        time.sleep(0.05)
    assert [type(m).__name__ for m in ctl.sent[:2]] == ["EdgeControl", "Command"]
    assert client.post("/control/scenario/ag_bozulmasi").status_code == 409  # one at a time
    status = client.get("/control/scenario").json()
    assert status["steps_fired"] == 2 and not status["done"]
    client.post("/control/reset")  # stops the player
    time.sleep(0.4)


# --- the log fold ----------------------------------------------------------------------------
def row(rowid, station, mode, params=None, variables=None, acked=1, start="2016-06-11T00:00:00",
        end=None, label=None):  # fmt: skip
    return {
        "rowid": rowid, "cmd_id": f"c{rowid}", "station": station, "mode": mode,
        "params": json.dumps(params or {}), "variables": json.dumps(variables or ["pm25"]),
        "start_ts": start, "end_ts": end, "label": label, "acked": acked, "error": None,
    }  # fmt: skip


def test_active_state_folds_interventions_network_edge_and_fleet():
    rows = [
        row(1, "Dongsi", "manual", {"value": 9}, label="a", end="2016-06-11T03:00:00"),
        row(2, "Huairou", "ramp", {"delta": 50}, label="b"),
        row(3, "Gucheng", "offline", label="gone"),
        row(4, "Gucheng", "replay", variables=["pm25"]),  # brings Gucheng back
        row(5, "all", "net", {"loss_rate": 0.2, "reset": False}),
        row(6, "Dongsi", "net", {"loss_rate": 0.5, "reset": False}),
        row(7, "Dongsi", "net", {"reset": True}),
        row(8, "edge", "filter", {"filter": "off"}),
        row(9, "fleet", "speedup", {"value": 7200}),
        row(10, "fleet", "pause"),
        row(11, "Huairou", "manual", {"value": 1}, acked=0),  # refused: never active
    ]
    st = active_state(rows, "2016-06-11T05:00:00")
    assert [i["label"] for i in st["interventions"]] == ["b"]  # a expired, gone replayed away
    assert list(st["network"]) == ["all"] and st["network"]["all"]["loss_rate"] == 0.2
    assert st["edge_filter"] == "off"
    assert st["fleet"] == {"paused": True, "speedup": 7200}
    assert [i["label"] for i in active_state(rows, "2016-06-11T01:00:00")["interventions"]] == [
        "a",
        "b",
    ]


def test_a_fleet_reset_drops_interventions_and_network_but_not_filter_or_speed():
    rows = [
        row(1, "Dongsi", "manual", {"value": 9}),
        row(2, "all", "net", {"loss_rate": 0.2, "reset": False}),
        row(3, "edge", "filter", {"filter": "off"}),
        row(4, "fleet", "speedup", {"value": 3600}),
        row(5, "fleet", "reset"),
        row(6, "Huairou", "scale", {"factor": 2}),
    ]
    st = active_state(rows, None)
    assert [i["station"] for i in st["interventions"]] == ["Huairou"]
    assert st["network"] == {} and st["edge_filter"] == "off" and st["fleet"]["speedup"] == 3600


def test_scorecard_endpoint_labels_its_reference(stack, tmp_path):
    client, _ = stack(truth=Truth(pd.DataFrame({"station": ["Dongsi"], "ts": [T0], "pm25": [1.0],
                                                "pm10": [2.0]}), {}))  # fmt: skip
    body = client.get("/control/scorecard").json()
    assert body["rows"] == [] and body["reference"] is None
    client2, _ = stack(truth=None)
    assert client2.get("/control/active").json()["sim_now"] == T0.isoformat()
