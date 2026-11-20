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


def test_live_warnings_apply_the_margin_and_the_cooldown():
    p = OnlinePredictor(CFG, None, 0, ["A"], thresholds={"150": {"6": 20, "24": 0}}, cooldown_h=6)
    rows = []
    for hour in range(14):
        ts = (T0 + timedelta(hours=hour)).isoformat()
        rows.append({"station": "A", "made_at_ts": ts, "horizon": 6, "yhat": 135.0})  # > 150 - 20
        rows.append({"station": "A", "made_at_ts": ts, "horizon": 24, "yhat": 135.0})  # < 150 - 0
    warns = []
    for i in range(0, len(rows), 2):
        warns += p.make_warnings(rows[i : i + 2])
    assert [w["horizon"] for w in warns] == [6, 6, 6]  # the 24 h forecast never crosses 150
    hours = [
        (pd.Timestamp(w["made_at_ts"]) - pd.Timestamp(T0)) / pd.Timedelta(hours=1) for w in warns
    ]
    assert hours == [0.0, 6.0, 12.0]  # opens, 5 h suppressed, re-opens while still above
    assert (
        warns[0]["threshold"] == 150.0
        and warns[0]["delta"] == 20.0
        and warns[0]["basis"] == "point"
    )
    assert (
        OnlinePredictor(CFG, None, 0, ["A"]).make_warnings(rows) == []
    )  # no thresholds: no warnings


def test_warning_message_schema_round_trips_and_rejects_extra_fields():
    import pytest as _pytest
    from pydantic import ValidationError

    from airq.iot.schemas import WarningMsg

    w = {
        "station": "A",
        "made_at_ts": "2016-03-01T00:00:00",
        "horizon": 6,
        "threshold": 150.0,
        "yhat": 160.0,
        "delta": 10.0,
        "basis": "point",
        "sent_at": "2026-11-19T12:00:00.100",
    }
    assert WarningMsg.from_json(WarningMsg(**w).to_json()).horizon == 6
    with _pytest.raises(ValidationError):
        WarningMsg(**w, extra=1)


def test_a_long_offline_station_is_not_waited_for():
    p = make(stations=("A", "B", "C"), wait_s=0.5)
    p.set_status("C", "offline", now=0.0)  # announced offline at t = 0
    p.add(msg("A", 1), now=1.0)
    p.add(msg("B", 1), now=1.0)
    assert p.ready(now=1.0) == [pd.Timestamp(T0 + timedelta(hours=1))]  # no wait for C
    p.predict(pd.Timestamp(T0 + timedelta(hours=1)))
    assert p.expired == 1  # the hour still counts as having a missing station


def test_the_last_readings_of_a_station_that_just_went_offline_are_still_awaited():
    """The status message overtakes the telemetry that is still travelling through the edge."""
    p = make(stations=("A", "B"), wait_s=0.5)
    p.add(msg("A", 0), now=1.0)
    p.set_status("B", "offline", now=1.0)  # B shut down cleanly; its last reading is in flight
    assert p.ready(now=1.1) == []  # inside the grace period: keep waiting
    p.add(msg("B", 0), now=1.2)  # ...and the reading arrives
    assert p.ready(now=1.2) == [pd.Timestamp(T0)]
    p.predict(pd.Timestamp(T0))
    assert p.expired == 0 and p.late_dropped == 0  # nothing was predicted early


def test_a_station_that_comes_back_is_waited_for_again():
    p = make(stations=("A", "B"), wait_s=0.5)
    p.set_status("B", "offline", now=0.0)
    p.set_status("B", "online", now=2.0)
    p.add(msg("A", 5), now=3.0)
    assert p.ready(now=3.1) == []  # B is expected again
    assert p.ready(now=3.5) == [pd.Timestamp(T0 + timedelta(hours=5))]


def test_unknown_status_payloads_change_nothing_and_the_option_can_be_turned_off():
    p = make()
    p.set_status("B", "weird")
    assert p.offline == {}
    q = OnlinePredictor(CFG, None, 0, ["A", "B"], wait_s=0.5, skip_offline=False)
    q.set_status("B", "offline", now=0.0)
    q.add(msg("A", 1), now=5.0)
    assert q.ready(now=5.1) == []  # with the option off the old behaviour (always wait) remains
