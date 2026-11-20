"""Tests that need a real MQTT broker (marker `broker`); the `broker` fixture starts amqtt."""

import json
import subprocess
import sys
import threading
import time

import numpy as np
import pandas as pd
import pytest

from airq.devices.fleet import run_fleet
from airq.devices.virtual_sensor import VirtualSensor
from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import Heartbeat, Telemetry

pytestmark = pytest.mark.broker


def _wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _subscriber(broker, filters, client_id="test-sub"):
    received: list[tuple[str, bytes, bool]] = []
    client = make_client(client_id)

    def on_message(_c, _u, msg):
        received.append((msg.topic, msg.payload, msg.retain))

    client.on_message = on_message
    connect_blocking(client, *broker)
    for f in filters:
        client.subscribe(f, qos=1)
    time.sleep(0.3)
    return client, received


def synthetic_raw(stations, hours=6):
    ts = pd.date_range("2016-03-01", periods=hours, freq="h")
    frames = []
    for i, s in enumerate(stations):
        d = pd.DataFrame({"station": s, "ts": ts, "pm25": np.arange(hours) + 10.0 * i})
        for c in ["pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]:
            d[c] = 1.0
        d["wd"] = "N"
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    if hours > 2:  # one missing PM2.5 reading at the third hour of the first station
        raw.loc[(raw["station"] == stations[0]) & (raw["ts"] == ts[2]), "pm25"] = np.nan
    return raw


def test_qos1_publish_subscribe_round_trip(broker):
    sub, got = _subscriber(broker, ["airq/test/#"])
    pub = make_client("test-pub")
    connect_blocking(pub, *broker)
    info = pub.publish("airq/test/x", "hello", qos=1)
    info.wait_for_publish(timeout=5)
    # amqtt may also hand over retained messages of other topics: look at our own topic only
    assert _wait(lambda: any(t == "airq/test/x" for t, _, _ in got))
    mine = [p for t, p, _ in got if t == "airq/test/x"]
    assert mine[0] == b"hello"
    disconnect(pub)
    disconnect(sub)


def test_fleet_publishes_ordered_telemetry_with_monotonic_seq_and_null_for_missing(broker):
    stations = ["Alpha", "Beta"]
    sub, got = _subscriber(broker, [topics.RAW_ALL, topics.HEARTBEAT_ALL, topics.STATUS_ALL])
    summary = run_fleet(
        synthetic_raw(stations, 6), stations, "2016-03-01 00:00", "2016-03-01 05:00",
        *broker, speedup=0,
    )  # fmt: skip
    assert summary["messages"] == 12
    assert _wait(lambda: sum(t.endswith("/telemetry") for t, _, _ in got) == 12)
    tele = [Telemetry.from_json(p) for t, p, _ in got if t.endswith("/telemetry")]
    for st in stations:
        seqs = [m.seq for m in tele if m.station == st]
        assert seqs == list(range(6))  # monotonic, no gaps
    # Each station is its own MQTT connection: per-station order is guaranteed, cross-station
    # arrival order is NOT (this is why the predictor waits for neighbors, spec 8.5).
    for st in stations:
        times = [m.ts for m in tele if m.station == st]
        assert times == sorted(times)
    by_ts: dict = {}
    for m in tele:
        by_ts.setdefault(m.ts, set()).add(m.station)
    assert all(v == set(stations) for v in by_ts.values()) and len(by_ts) == 6
    missing = next(m for m in tele if m.station == "Alpha" and m.seq == 2)
    assert missing.pm25 is None and missing.pm10 == 1.0  # NaN -> null
    assert json.loads(next(p for t, p, _ in got if t.endswith("/telemetry")))["schema_version"] == 1
    # heartbeats are QoS 0 and may trail the QoS 1 telemetry: wait for them before counting
    expected_beats = 6 * 2 * 2  # 2 per sim hour (every 30 sim minutes) x 2 stations
    _wait(lambda: sum(t.endswith("/heartbeat") for t, _, _ in got) >= expected_beats, 5)
    beats = [Heartbeat.from_json(p) for t, p, _ in got if t.endswith("/heartbeat")]
    assert len(beats) == expected_beats
    disconnect(sub)


def test_clean_shutdown_publishes_retained_offline(broker):
    stations = ["Gamma"]
    run_fleet(synthetic_raw(stations, 2), stations, "2016-03-01 00:00", "2016-03-01 01:00",
              *broker, speedup=0)  # fmt: skip
    sub, got = _subscriber(broker, [topics.STATUS_ALL], "late-sub")
    assert _wait(lambda: any(t == "airq/Gamma/status" for t, _, _ in got))
    topic, payload, retained = next(g for g in got if g[0] == "airq/Gamma/status")
    assert payload == b"offline" and retained is True  # a late subscriber sees the last state
    disconnect(sub)


def test_lwt_sets_offline_when_the_device_process_is_killed(broker):
    host, port = broker
    sub, got = _subscriber(broker, [topics.STATUS_ALL], "lwt-watcher")
    code = (
        "import time, pandas as pd;"
        "from airq.devices.virtual_sensor import VirtualSensor;"
        "df = pd.DataFrame({'station': ['Delta'], 'ts': [pd.Timestamp('2016-03-01')]});"
        f"s = VirtualSensor('Delta', df, '{host}', {port}); s.connect(); time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        assert _wait(
            lambda: any(g[1] == b"online" and g[0] == "airq/Delta/status" for g in got), 20
        )
        proc.kill()  # abrupt death: no clean disconnect -> broker publishes the last will
        proc.wait(timeout=10)
        assert _wait(
            lambda: any(g[1] == b"offline" and g[0] == "airq/Delta/status" for g in got), 20
        )
    finally:
        proc.kill()
        disconnect(sub)


def test_ctrl_c_style_stop_ends_the_fleet_and_publishes_offline(broker):
    stations = ["Epsilon"]
    sub, got = _subscriber(broker, [topics.STATUS_ALL], "stop-watcher")
    stop = threading.Event()
    result = {}
    thread = threading.Thread(
        target=lambda: result.update(
            run_fleet(synthetic_raw(stations, 48), stations, "2016-03-01 00:00", "2016-03-02 23:00",
                      *broker, speedup=3600, stop=stop)
        )
    )  # fmt: skip
    thread.start()
    assert _wait(lambda: any(g[1] == b"online" and g[0] == "airq/Epsilon/status" for g in got), 20)
    stop.set()
    thread.join(timeout=20)
    assert not thread.is_alive() and result["messages"] < 48
    assert _wait(lambda: got and got[-1][1] == b"offline", 10)
    disconnect(sub)


def test_virtual_sensor_unit_behaviour_without_broker():
    ts = pd.to_datetime(["2016-03-01 00:00", "2016-03-01 02:00"])
    df = pd.DataFrame({"station": ["Z", "Z"], "ts": ts, "pm25": [5.0, np.nan], "wd": ["N", None]})
    s = VirtualSensor("Z", df, "127.0.0.1", 1)
    a = s.build_reading(pd.Timestamp("2016-03-01 00:00"))
    absent = s.build_reading(pd.Timestamp("2016-03-01 01:00"))  # hour not in the record
    nan = s.build_reading(pd.Timestamp("2016-03-01 02:00"))
    assert (a.seq, absent.seq, nan.seq) == (0, 1, 2)
    assert a.pm25 == 5.0 and a.wd == "N"
    assert absent.pm25 is None and nan.pm25 is None and nan.wd is None
    assert s.device_id == "z-01"


def test_broker_smoke_script_reports_ok(broker):
    host, port = broker
    out = subprocess.run(
        [sys.executable, "-m", "scripts.broker_smoke", "--broker", f"{host}:{port}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0 and out.stdout.startswith("OK: pub/sub round trip")


def test_netem_loss_drops_messages_but_keeps_seq_so_the_gap_is_visible(broker):
    from airq.devices.netem import NetEm, NetParams

    stations = ["NetA", "NetB"]
    sub, got = _subscriber(broker, [topics.RAW_ALL], "netem-watch")
    summary = run_fleet(
        synthetic_raw(stations, 200), stations, "2016-03-01 00:00", "2016-03-09 07:00",
        *broker, speedup=0, netem=NetEm(NetParams(loss_rate=0.3), seed=1),
    )  # fmt: skip
    assert summary["messages"] == 400 and 0.2 < summary["dropped"] / 400 < 0.4
    expected = summary["messages"] - summary["dropped"]

    def unique() -> set[tuple[str, int]]:
        # QoS 1 is at-least-once (a broker may redeliver): count distinct (station, seq) pairs.
        # amqtt also hands retained `status` messages to wildcard subscribers: keep raw topics only.
        raw = [p for t, p, _ in list(got) if t.startswith("airq/raw/")]
        return {(m.station, m.seq) for m in map(Telemetry.from_json, raw)}

    assert _wait(lambda: len(unique()) == expected)
    seen = unique()
    lost = sum(200 - len({s for st2, s in seen if st2 == st}) for st in stations)
    assert lost == summary["dropped"]  # every dropped reading is one missing seq
    disconnect(sub)


def test_netem_delay_shows_up_in_the_end_to_end_latency(broker):
    from datetime import datetime

    from airq.devices.netem import NetEm, NetParams

    sub, got = _subscriber(broker, [topics.RAW_ALL], "netem-delay-watch")
    run_fleet(
        synthetic_raw(["DelA"], 6), ["DelA"], "2016-03-01 00:00", "2016-03-01 05:00",
        *broker, speedup=0, netem=NetEm(NetParams(delay_ms=200), seed=2),
    )  # fmt: skip
    assert _wait(lambda: len(got) == 6)
    arrived = datetime.now()
    lat = [Telemetry.from_json(p).sent_at for _, p, _ in got]
    assert all((arrived - sent).total_seconds() >= 0.2 for sent in lat)  # >= the emulated delay
    disconnect(sub)


def test_offline_devices_announce_offline_and_publish_no_data(broker):
    stations = ["UpA", "DownB"]
    sub, got = _subscriber(broker, [topics.RAW_ALL, topics.STATUS_ALL], "offline-watch")
    summary = run_fleet(
        synthetic_raw(stations, 4), stations, "2016-03-01 00:00", "2016-03-01 03:00",
        *broker, speedup=0, offline=["DownB"],
    )  # fmt: skip
    assert summary["devices"] == 1 and summary["offline_devices"] == 1 and summary["messages"] == 4
    assert _wait(lambda: sum(t.endswith("/telemetry") for t, _, _ in got) == 4)
    assert all("DownB" not in t for t, _, _ in got if t.endswith("/telemetry"))
    assert _wait(lambda: any(t == "airq/DownB/status" and p == b"offline" for t, p, _ in got))
    disconnect(sub)
