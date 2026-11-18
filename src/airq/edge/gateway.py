"""Edge gateway: validate raw telemetry, flag data quality, track `seq`, forward to the server.

raw (airq/raw/+/telemetry) -> [validate, quality flags, seq accounting, optional filter]
                           -> airq/edge/{station}/telemetry   (+ counters on airq/edge/stats)

Run: python -m airq.edge.gateway [--broker 127.0.0.1:1883]
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field

from pydantic import ValidationError

from airq.edge.quality import (
    QualityParams,
    StreamChecker,
    value_is_untrustworthy,
)
from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import Telemetry

log = logging.getLogger("airq.edge")
SEQ_GAP = "seq_gap"
DUPLICATE = "duplicate"
RECENT_SEQS = 512


@dataclass
class EdgeCounters:
    received: int = 0
    invalid: int = 0
    forwarded: int = 0
    values_filtered: int = 0  # PM2.5 values replaced by null (filter ON)
    seq_lost: int = 0  # messages missing in the seq stream
    duplicates: int = 0
    out_of_order: int = 0
    flags: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "received": self.received,
            "invalid": self.invalid,
            "forwarded": self.forwarded,
            "values_filtered": self.values_filtered,
            "seq_lost": self.seq_lost,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "flags": dict(self.flags),
        }


class _StationState:
    def __init__(self, params: QualityParams):
        self.checker = StreamChecker(params)
        self.last_seq: int | None = None
        self.recent: deque[int] = deque(maxlen=RECENT_SEQS)


class EdgeGateway:
    """Pure message processor (no MQTT): easy to test; `run()` wires it to a broker."""

    def __init__(self, params: QualityParams, filter_on: bool = True):
        self.params = params
        self.filter_on = filter_on
        self.counters = EdgeCounters()
        self._states: dict[str, _StationState] = {}
        self._lock = threading.Lock()

    def set_filter(self, on: bool) -> None:
        self.filter_on = on

    def process(self, payload: bytes | str) -> tuple[str, str] | None:
        """Return (topic, json) to forward, or None when the message is invalid (dropped)."""
        with self._lock:
            c = self.counters
            c.received += 1
            try:
                msg = Telemetry.from_json(payload)
            except ValidationError as exc:
                c.invalid += 1
                log.warning("invalid telemetry dropped: %s", str(exc).splitlines()[0])
                return None
            st = self._states.setdefault(msg.station, _StationState(self.params))
            flags: list[str] = []
            duplicate = msg.seq in st.recent
            if duplicate:
                c.duplicates += 1
                flags.append(DUPLICATE)  # forwarded (the server's upsert is idempotent), no state
            else:
                if st.last_seq is not None:
                    if msg.seq > st.last_seq + 1:
                        c.seq_lost += msg.seq - st.last_seq - 1
                        flags.append(SEQ_GAP)
                    elif msg.seq < st.last_seq:  # a late message fills an earlier "gap"
                        c.out_of_order += 1
                        c.seq_lost = max(0, c.seq_lost - 1)
                st.last_seq = msg.seq if st.last_seq is None else max(st.last_seq, msg.seq)
                st.recent.append(msg.seq)
                flags.extend(st.checker.update(msg.pm25, msg.pm10))
            for f in flags:
                c.flags[f] = c.flags.get(f, 0) + 1
            if self.filter_on and value_is_untrustworthy(flags) and msg.pm25 is not None:
                msg.pm25 = None  # untrusted value -> null (becomes NaN downstream)
                c.values_filtered += 1
            msg.quality_flags = flags
            c.forwarded += 1
            return topics.topic(topics.EDGE_TELEMETRY, msg.station), msg.to_json()

    def stats(self) -> dict:
        with self._lock:
            return {**self.counters.as_dict(), "filter_on": self.filter_on}


def run(
    params: QualityParams,
    host: str,
    port: int,
    filter_on: bool = True,
    stop: threading.Event | None = None,
    stats_every_s: float = 10.0,
) -> EdgeGateway:
    """Connect to the broker and run the gateway until `stop` is set."""
    stop = stop or threading.Event()
    gw = EdgeGateway(params, filter_on)
    client = make_client("edge-gateway")

    def on_message(c, _u, msg):
        out = gw.process(msg.payload)
        if out is not None:
            c.publish(out[0], out[1], qos=topics.EDGE_TELEMETRY.qos)

    client.on_message = on_message
    connect_blocking(client, host, port)
    client.subscribe(topics.RAW_ALL, qos=topics.RAW_TELEMETRY.qos)
    try:
        while not stop.wait(stats_every_s):
            client.publish(topics.topic(topics.EDGE_STATS), json.dumps(gw.stats()), qos=0)
    finally:
        client.publish(topics.topic(topics.EDGE_STATS), json.dumps(gw.stats()), qos=0)
        disconnect(client)
    return gw


def main() -> None:
    from airq.pipelines.edge import load_params

    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="127.0.0.1:1883")
    ap.add_argument("--filter", choices=["on", "off"], default="on")
    args = ap.parse_args()
    host, port = args.broker.rsplit(":", 1)
    stop = threading.Event()
    try:
        run(load_params(), host, int(port), args.filter == "on", stop)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
