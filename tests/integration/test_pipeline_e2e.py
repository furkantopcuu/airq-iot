"""Virtual devices -> MQTT -> edge gateway -> ingest -> SQLite, on every available broker."""

import json
import threading
import time

import numpy as np
import pandas as pd
import pytest

from airq.devices.fleet import run_fleet
from airq.edge.gateway import run as run_gateway
from airq.edge.quality import QualityParams
from airq.server import db
from airq.server.ingest import Ingest

pytestmark = pytest.mark.broker
P = QualityParams(lo=0, hi=999, stuck_n=4, tau_rate=300, pm_eps=0.1, pm_c=50)


def _raw(stations, hours=24, stuck=None):
    ts = pd.date_range("2016-03-01", periods=hours, freq="h")
    rng = np.random.default_rng(0)
    frames = []
    for st in stations:
        d = pd.DataFrame(
            {"station": st, "ts": ts, "pm25": 60 + np.arange(hours) * 1.0 + rng.normal(0, 2, hours)}
        )
        d["pm25"] = d["pm25"].round()
        for c in ["pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]:
            d[c] = 100.0 if c == "pm10" else 1.0
        d["wd"] = "N"
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    if stuck:
        st, a, b = stuck
        raw.loc[(raw["station"] == st) & (raw["ts"] >= ts[a]) & (raw["ts"] <= ts[b]), "pm25"] = 42.0
    return raw


def _wait(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _run_pipeline(broker, tmp_path, raw, stations, hours, filter_on=True):
    ingest = Ingest(tmp_path / "e2e.db")
    ingest.start(*broker)
    stop = threading.Event()
    holder = {}
    gw_thread = threading.Thread(
        target=lambda: holder.update(gw=run_gateway(P, *broker, filter_on, stop, stats_every_s=0.5))
    )
    gw_thread.start()
    time.sleep(1.0)  # let the gateway and ingest subscribe
    run_fleet(
        raw, stations, "2016-03-01 00:00", f"2016-03-01 {hours - 1:02d}:00", *broker, speedup=0
    )
    con = db.connect(tmp_path / "e2e.db", read_only=True)
    n_expected = len(stations) * hours
    ok = _wait(lambda: con.execute("SELECT COUNT(*) FROM readings").fetchone()[0] >= n_expected)
    ingest.flush()
    stop.set()
    gw_thread.join(timeout=10)
    ingest.stop()
    return con, ok, ingest


def test_end_to_end_no_loss_idempotent_and_edge_filter_on(broker, tmp_path):
    stations = ["Alpha", "Beta"]
    raw = _raw(stations, 24, stuck=("Alpha", 5, 12))
    con, ok, ingest = _run_pipeline(broker, tmp_path, raw, stations, 24, filter_on=True)
    assert ok, "not all readings reached SQLite"
    assert con.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 48
    for st in stations:  # seq gap = 0 end to end
        seqs = [
            r[0] for r in con.execute("SELECT seq FROM readings WHERE station=? ORDER BY ts", (st,))
        ]
        assert seqs == list(range(24))
    stuck_rows = con.execute(
        "SELECT ts, pm25 FROM readings WHERE station='Alpha' AND quality_flags LIKE '%stuck%'"
    ).fetchall()
    assert len(stuck_rows) == 5  # hours 8..12: the 4th equal value onwards
    assert all(r["pm25"] is None for r in stuck_rows)  # filter ON: untrusted value removed
    clean = con.execute(
        "SELECT COUNT(*) FROM readings WHERE station='Beta' AND pm25 IS NULL"
    ).fetchone()[0]
    assert clean == 0
    # the shared test broker also holds retained status of other tests' stations: look at ours
    status = {
        k: v for k, v in con.execute("SELECT station, status FROM device_status") if k in stations
    }
    assert status == {"Alpha": "offline", "Beta": "offline"}  # clean shutdown of the fleet
    assert ingest.stats["unique"] == 48 and ingest.stats["invalid"] == 0
    flags = [json.loads(r[0]) for r in con.execute("SELECT quality_flags FROM readings")]
    assert sum("stuck" in f for f in flags) == 5 and sum(f == [] for f in flags) == 43


def test_end_to_end_with_edge_filter_off_keeps_the_stuck_values(broker, tmp_path):
    stations = ["Alpha"]
    raw = _raw(stations, 16, stuck=("Alpha", 4, 10))
    con, ok, _ = _run_pipeline(broker, tmp_path, raw, stations, 16, filter_on=False)
    assert ok
    rows = con.execute("SELECT pm25 FROM readings WHERE quality_flags LIKE '%stuck%'").fetchall()
    assert len(rows) == 4 and all(r["pm25"] == 42.0 for r in rows)  # flagged but kept
