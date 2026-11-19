from datetime import datetime, timedelta

import pandas as pd

from airq.config import load_config
from airq.iot.schemas import Telemetry
from airq.server.predictor import OnlinePredictor

CFG = load_config()
T0 = datetime(2016, 3, 1)


def msg(station, hour, pm25=50.0):
    return Telemetry(
        device_id=f"{station.lower()}-01", station=station, seq=hour, ts=T0 + timedelta(hours=hour),
        sent_at=datetime.now(), pm25=pm25,
    )  # fmt: skip


def make(stations=("A", "B"), wait_s=0.5):
    return OnlinePredictor(CFG, None, 0, list(stations), wait_s=wait_s)


def test_hour_is_ready_when_all_stations_arrived():
    p = make()
    p.add(msg("A", 0), now=0.0)
    assert p.ready(now=0.1) == []  # B has not arrived yet: wait
    p.add(msg("B", 0), now=0.2)
    assert p.ready(now=0.2) == [pd.Timestamp(T0)]


def test_hour_is_released_after_the_wait_deadline_with_a_missing_station():
    p = make(wait_s=0.5)
    p.add(msg("A", 0), now=0.0)
    assert p.ready(now=0.49) == []
    assert p.ready(now=0.5) == [pd.Timestamp(T0)]  # B counts as missing from now on
    p.predict(pd.Timestamp(T0))
    assert p.expired == 1


def test_hours_are_processed_in_order_and_never_overtake():
    p = make(wait_s=0.5)
    p.add(msg("A", 0), now=0.0)  # hour 0 incomplete
    p.add(msg("A", 1), now=0.0)
    p.add(msg("B", 1), now=0.0)  # hour 1 complete, but must wait behind hour 0
    assert p.ready(now=0.1) == []
    assert p.ready(now=0.6) == [pd.Timestamp(T0), pd.Timestamp(T0 + timedelta(hours=1))]


def test_late_messages_for_finished_hours_are_dropped_not_repredicted():
    p = make()
    p.add(msg("A", 0), now=0.0)
    p.add(msg("B", 0), now=0.0)
    p.predict(pd.Timestamp(T0))  # (not warm yet -> no rows) hour 0 is now done
    p.add(msg("B", 0, pm25=99.0), now=1.0)  # QoS1 redelivery / late arrival
    assert p.late_dropped == 1 and p.ready(now=2.0) == []


def test_unknown_station_is_ignored_and_buffer_is_pruned():
    p = make(stations=("A",))
    p.add(msg("Z", 0), now=0.0)
    assert p.ready(now=1.0) == []
    for h in range(0, 400):
        p.add(msg("A", h), now=0.0)
    p._prune(pd.Timestamp(T0 + timedelta(hours=399)))  # what predict() does after each hour
    assert len(p.buf["A"]) <= p.history_h + 25  # old hours are dropped
