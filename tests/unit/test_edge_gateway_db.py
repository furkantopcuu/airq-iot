import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from airq.edge.gateway import DUPLICATE, SEQ_GAP, EdgeGateway
from airq.edge.quality import STUCK, QualityParams
from airq.iot.schemas import Telemetry
from airq.server import db
from airq.server.ingest import telemetry_row

P = QualityParams(lo=0, hi=999, stuck_n=4, tau_rate=100, pm_eps=0.1, pm_c=10)
T0 = datetime(2016, 3, 1)


def msg(seq, pm25=50.0, pm10=80.0, station="Dongsi"):
    return Telemetry(
        device_id="dongsi-01", station=station, seq=seq, ts=T0 + timedelta(hours=seq),
        sent_at=datetime.now(), pm25=pm25, pm10=pm10, wd="N",
    ).to_json()  # fmt: skip


def out(gw, payload):
    result = gw.process(payload)
    return None if result is None else (result[0], Telemetry.from_json(result[1]))


def test_invalid_messages_are_counted_and_not_forwarded():
    gw = EdgeGateway(P)
    assert gw.process(b"not json") is None
    assert gw.process(json.dumps({"station": "X"})) is None
    assert gw.stats()["invalid"] == 2 and gw.stats()["forwarded"] == 0


def test_valid_message_is_forwarded_to_the_edge_topic_with_flags():
    gw = EdgeGateway(P)
    topic, m = out(gw, msg(0))
    assert topic == "airq/edge/Dongsi/telemetry" and m.quality_flags == [] and m.pm25 == 50.0


def test_seq_gap_duplicate_and_out_of_order_accounting():
    gw = EdgeGateway(P)
    for s in (0, 1, 4):  # 2 and 3 are lost
        out(gw, msg(s, pm25=50.0 + s))
    assert gw.stats()["seq_lost"] == 2
    _, m = out(gw, msg(4, pm25=54.0))  # QoS1 redelivery
    assert DUPLICATE in m.quality_flags and gw.stats()["duplicates"] == 1
    out(gw, msg(2, pm25=52.0))  # late arrival fills one gap
    assert gw.stats()["out_of_order"] == 1 and gw.stats()["seq_lost"] == 1


def test_first_message_after_a_gap_carries_the_seq_gap_flag():
    gw = EdgeGateway(P)
    out(gw, msg(0))
    _, m = out(gw, msg(3))
    assert SEQ_GAP in m.quality_flags


def test_filter_on_nulls_a_stuck_value_but_off_passes_it_through():
    for on in (True, False):
        gw = EdgeGateway(P, filter_on=on)
        last = None
        for s in range(6):
            _, last = out(gw, msg(s, pm25=33.0, pm10=60.0))
        assert STUCK in last.quality_flags
        assert (last.pm25 is None) == on  # ON removes the value, OFF forwards it as-is
    assert gw.stats()["filter_on"] is False


def test_filter_can_be_switched_at_runtime_and_counts_removed_values():
    gw = EdgeGateway(P, filter_on=False)
    for s in range(5):
        out(gw, msg(s, pm25=7.0, pm10=60.0))
    assert gw.stats()["values_filtered"] == 0
    gw.set_filter(True)
    _, m = out(gw, msg(5, pm25=7.0, pm10=60.0))
    assert m.pm25 is None and gw.stats()["values_filtered"] == 1


def test_missing_value_is_flagged_but_not_counted_as_filtered():
    gw = EdgeGateway(P)
    _, m = out(gw, msg(0, pm25=None))
    assert m.quality_flags == ["missing"] and gw.stats()["values_filtered"] == 0


# --- database ----------------------------------------------------------------------------
def _row(seq=0, pm25=10.0):
    m = Telemetry.from_json(msg(seq, pm25=pm25))
    return telemetry_row(m, datetime.now())


def test_upsert_is_idempotent_and_counts_duplicates(tmp_path):
    con = db.connect(tmp_path / "t.db")
    assert db.upsert_reading(con, _row(0, pm25=10.0)) is True
    assert db.upsert_reading(con, _row(0, pm25=999.0)) is False  # same (station, ts)
    con.commit()
    rows = con.execute("SELECT pm25, dup_count FROM readings").fetchall()
    assert len(rows) == 1 and rows[0]["dup_count"] == 1
    assert rows[0]["pm25"] == 10.0  # the value does not change
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_schema_has_all_tables_and_reader_cannot_write(tmp_path):
    con = db.connect(tmp_path / "t.db")
    db.set_device_status(con, "Dongsi", "online", "2016-03-01T00:00:00")
    db.set_device_status(con, "Dongsi", "offline", "2016-03-01T01:00:00")
    con.commit()
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"readings", "predictions", "warnings", "device_status", "interventions",
            "system_events"} <= names  # fmt: skip
    assert con.execute("SELECT status FROM device_status").fetchone()[0] == "offline"
    ro = db.connect(tmp_path / "t.db", read_only=True)
    assert ro.execute("SELECT COUNT(*) FROM device_status").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM device_status")
