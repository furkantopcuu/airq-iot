"""Virtual IoT device: replays one station's recorded data as MQTT telemetry."""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import MEASUREMENTS, Heartbeat, Telemetry


def _clean(v):
    """NaN/NA -> None so missing measurements are sent as JSON null."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA:
        return None
    return v


class VirtualSensor:
    """One station = one MQTT client (client_id `<station>-01`) with LWT, heartbeat and `seq`."""

    def __init__(self, station: str, readings: pd.DataFrame, host: str, port: int):
        self.station = station
        self.device_id = f"{station.lower()}-01"
        self.host, self.port = host, port
        self.readings = readings.drop_duplicates("ts").set_index("ts")
        self.seq = 0  # monotonically increasing per device
        self.client = None
        self._last_info = None

    # --- lifecycle -------------------------------------------------------------------------
    def connect(self) -> None:
        status = topics.topic(topics.STATUS, self.station)
        self.client = make_client(
            self.device_id, lwt=(status, topics.OFFLINE, topics.STATUS.qos, topics.STATUS.retained)
        )
        connect_blocking(self.client, self.host, self.port)
        self._publish(topics.STATUS, topics.ONLINE)

    def close(self) -> None:
        """Clean shutdown: publish `offline` first, then drop the connection."""
        if self.client is None:
            return
        self._publish(topics.STATUS, topics.OFFLINE)
        if self._last_info is not None:
            self._last_info.wait_for_publish(timeout=5)
        disconnect(self.client)
        self.client = None

    # --- publishing ------------------------------------------------------------------------
    def _publish(self, spec: topics.TopicSpec, payload: str) -> None:
        self._last_info = self.client.publish(
            topics.topic(spec, self.station), payload, qos=spec.qos, retain=spec.retained
        )

    def build_reading(self, ts: datetime, now: datetime | None = None) -> Telemetry:
        ts = pd.Timestamp(ts)
        row = self.readings.loc[ts] if ts in self.readings.index else None
        # a missing row or column is "no data" -> null, never an error
        values = {m: (_clean(row.get(m)) if row is not None else None) for m in MEASUREMENTS}
        wd = _clean(row.get("wd")) if row is not None else None
        msg = Telemetry(
            device_id=self.device_id,
            station=self.station,
            seq=self.seq,
            ts=ts.to_pydatetime(),
            sent_at=now or datetime.now(),
            wd=wd,
            **values,
        )
        self.seq += 1
        return msg

    def publish_reading(self, ts: datetime) -> Telemetry:
        msg = self.build_reading(ts)
        self._publish(topics.RAW_TELEMETRY, msg.to_json())
        return msg

    def publish_heartbeat(self, ts: datetime) -> None:
        hb = Heartbeat(
            device_id=self.device_id,
            station=self.station,
            seq=max(self.seq - 1, 0),
            ts=pd.Timestamp(ts).to_pydatetime(),
            sent_at=datetime.now(),
        )
        self._publish(topics.HEARTBEAT, hb.to_json())
