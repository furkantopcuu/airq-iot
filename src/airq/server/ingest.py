"""Ingest service: edge telemetry + device status -> SQLite (the single writer).

Run: python -m airq.server.ingest [--broker 127.0.0.1:1883] [--db data/airq.db]
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import MEASUREMENTS, Telemetry
from airq.server import db

_STOP = object()


def telemetry_row(msg: Telemetry, received_at: datetime) -> dict:
    row = {m: getattr(msg, m) for m in MEASUREMENTS}
    row.update(
        station=msg.station,
        ts=msg.ts.isoformat(),
        wd=msg.wd,
        seq=msg.seq,
        sent_at=msg.sent_at.isoformat(timespec="milliseconds"),
        received_at=received_at.isoformat(timespec="milliseconds"),
        quality_flags=json.dumps(msg.quality_flags or []),
    )
    return row


class Ingest:
    """Callbacks only enqueue; one writer thread owns the database connection."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.q: queue.Queue = queue.Queue()
        self.stats = {"received": 0, "invalid": 0, "unique": 0, "duplicates": 0}
        self._thread = threading.Thread(target=self._writer, name="ingest-writer", daemon=True)
        self._client = None

    # -- MQTT side ------------------------------------------------------------------------
    def on_message(self, _client, _userdata, msg) -> None:
        now = datetime.now()
        if msg.topic.endswith("/telemetry"):
            self.q.put(("telemetry", msg.payload, now))
        elif msg.topic.endswith("/status"):
            station = topics.station_from_topic(msg.topic)
            self.q.put(("status", (station, msg.payload.decode("utf-8", "replace")), now))

    def start(self, host: str, port: int) -> None:
        self._thread.start()
        self._client = make_client("ingest")
        self._client.on_message = self.on_message
        connect_blocking(self._client, host, port)
        self._client.subscribe(
            [(topics.EDGE_ALL, topics.EDGE_TELEMETRY.qos), (topics.STATUS_ALL, topics.STATUS.qos)]
        )

    def stop(self) -> None:
        if self._client is not None:
            disconnect(self._client)
        self.q.put(_STOP)
        self._thread.join(timeout=10)

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything queued so far is written (for tests/benchmarks)."""
        done = threading.Event()
        self.q.put(("flush", done, None))
        return done.wait(timeout)

    # -- writer thread --------------------------------------------------------------------
    def _writer(self) -> None:
        con = db.connect(self.db_path)
        try:
            while True:
                items = [self.q.get()]
                while len(items) < 500:  # batch commits for throughput
                    try:
                        items.append(self.q.get_nowait())
                    except queue.Empty:
                        break
                stop = False
                flushes = []
                for item in items:
                    if item is _STOP:
                        stop = True
                        continue
                    kind, payload, now = item
                    if kind == "flush":
                        flushes.append(payload)
                    elif kind == "telemetry":
                        self._write_telemetry(con, payload, now)
                    elif kind == "status":
                        db.set_device_status(con, payload[0], payload[1], now.isoformat())
                con.commit()
                for ev in flushes:
                    ev.set()
                if stop:
                    return
        finally:
            con.close()

    def _write_telemetry(self, con, payload: bytes, now: datetime) -> None:
        self.stats["received"] += 1
        try:
            msg = Telemetry.from_json(payload)
        except ValidationError:
            self.stats["invalid"] += 1
            return
        if db.upsert_reading(con, telemetry_row(msg, now)):
            self.stats["unique"] += 1
        else:
            self.stats["duplicates"] += 1


def main() -> None:
    from airq.config import load_config
    from airq.env import resolve_paths

    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="127.0.0.1:1883")
    ap.add_argument("--db", default=str(resolve_paths(cfg["paths"])["db"]))
    args = ap.parse_args()
    host, port = args.broker.rsplit(":", 1)
    ing = Ingest(args.db)
    ing.start(host, int(port))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        ing.stop()


if __name__ == "__main__":
    main()
