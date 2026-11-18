import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from airq.iot import topics
from airq.iot.schemas import Heartbeat, Telemetry

BASE = {
    "device_id": "dongsi-01",
    "station": "Dongsi",
    "seq": 10234,
    "ts": "2016-07-01T13:00:00",
    "sent_at": "2026-11-20T10:15:03.123",
    "schema_version": 1,
    "pm25": 81.0,
    "pm10": 110.0,
    "wd": "SE",
}


def test_valid_payload_round_trips_and_nulls_are_allowed():
    msg = Telemetry.from_json(json.dumps(BASE))
    assert msg.pm25 == 81.0 and msg.so2 is None  # unspecified measurement = null
    again = Telemetry.from_json(msg.to_json())
    assert again == msg
    assert isinstance(again.ts, datetime) and again.ts.tzinfo is None  # naive local time


def test_invalid_payloads_are_rejected():
    bad_cases = [
        {**BASE, "seq": -1},
        {**BASE, "schema_version": 2},
        {**BASE, "wd": "UP"},
        {**BASE, "pm25": "abc"},
        {**BASE, "unexpected": 1},
        {k: v for k, v in BASE.items() if k != "station"},
    ]
    for payload in bad_cases:
        with pytest.raises(ValidationError):
            Telemetry.model_validate(payload)
    with pytest.raises(ValidationError):
        Telemetry.from_json("not json")


def test_nan_and_infinity_are_not_valid_measurements():
    with pytest.raises(ValidationError):
        Telemetry.model_validate({**BASE, "pm25": float("nan")})
    with pytest.raises(ValidationError):
        Telemetry.model_validate({**BASE, "pm10": float("inf")})


def test_heartbeat_round_trip():
    hb = Heartbeat(
        device_id="x-01", station="X", seq=3, ts=datetime(2016, 1, 1, 0, 30), sent_at=datetime.now()
    )
    assert Heartbeat.from_json(hb.to_json()) == hb


def test_topic_table_matches_the_spec():
    assert topics.topic(topics.RAW_TELEMETRY, "Dongsi") == "airq/raw/Dongsi/telemetry"
    assert topics.topic(topics.STATUS, "Dongsi") == "airq/Dongsi/status"
    assert topics.topic(topics.EDGE_STATS) == "airq/edge/stats"
    assert (topics.STATUS.qos, topics.STATUS.retained) == (1, True)  # LWT status is retained
    assert (topics.RAW_TELEMETRY.qos, topics.RAW_TELEMETRY.retained) == (1, False)
    assert (topics.HEARTBEAT.qos, topics.EDGE_STATS.qos) == (0, 0)
    assert topics.CMD_ACK.qos == 1 and topics.WARNINGS.qos == 1


def test_topic_rejects_wildcards_and_missing_station():
    for bad in ("a/b", "a+b", "#", ""):
        with pytest.raises(ValueError):
            topics.topic(topics.RAW_TELEMETRY, bad)
    with pytest.raises(ValueError):
        topics.topic(topics.RAW_TELEMETRY)


def test_station_from_topic():
    assert topics.station_from_topic("airq/raw/Dongsi/telemetry") == "Dongsi"
    assert topics.station_from_topic("airq/edge/Huairou/telemetry") == "Huairou"
    assert topics.station_from_topic("airq/Tiantan/status") == "Tiantan"
    assert topics.station_from_topic("airq/Tiantan/heartbeat") == "Tiantan"
    assert topics.station_from_topic("airq/cmd/ack/Dongsi") == "Dongsi"
    assert topics.station_from_topic("airq/cmd/Dongsi") == "Dongsi"
    assert topics.station_from_topic("airq/warnings/Dongsi") == "Dongsi"
    with pytest.raises(ValueError):
        topics.station_from_topic("other/thing")
