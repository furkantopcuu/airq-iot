"""SQLite storage (WAL). One writer (ingest); the API opens read-only connections."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings(
  station TEXT, ts TEXT, pm25 REAL, pm10 REAL, so2 REAL, no2 REAL, co REAL, o3 REAL,
  temp REAL, pres REAL, dewp REAL, rain REAL, wd TEXT, wspm REAL,
  seq INTEGER, sent_at TEXT, received_at TEXT, quality_flags TEXT, dup_count INTEGER DEFAULT 0,
  PRIMARY KEY(station, ts));
CREATE TABLE IF NOT EXISTS predictions(
  station TEXT, made_at_ts TEXT, target_ts TEXT, horizon INTEGER,
  yhat REAL, q10 REAL, q90 REAL, n_neighbors INTEGER, model_version TEXT,
  PRIMARY KEY(station, made_at_ts, horizon));
CREATE TABLE IF NOT EXISTS warnings(
  station TEXT, made_at_ts TEXT, horizon INTEGER, threshold REAL, yhat REAL,
  basis TEXT, sent_at TEXT, PRIMARY KEY(station, made_at_ts, horizon, threshold));
CREATE TABLE IF NOT EXISTS device_status(station TEXT PRIMARY KEY, status TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS interventions(
  cmd_id TEXT PRIMARY KEY, station TEXT, variables TEXT, mode TEXT, params TEXT,
  start_ts TEXT, end_ts TEXT, label TEXT, acked INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS system_events(wall_ts TEXT, kind TEXT, payload TEXT);
"""

READING_COLUMNS = [
    "station", "ts", "pm25", "pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain",
    "wd", "wspm", "seq", "sent_at", "received_at", "quality_flags",
]  # fmt: skip

_UPSERT_READING = f"""
INSERT INTO readings({", ".join(READING_COLUMNS)})
VALUES ({", ".join("?" for _ in READING_COLUMNS)})
ON CONFLICT(station, ts) DO UPDATE SET dup_count = dup_count + 1
"""

_UPSERT_STATUS = """
INSERT INTO device_status(station, status, updated_at) VALUES (?, ?, ?)
ON CONFLICT(station) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
"""


def connect(path: Path | str, read_only: bool = False) -> sqlite3.Connection:
    """Open the database. Writers create the schema; read-only connections never write."""
    path = Path(path)
    if read_only:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        con.execute("PRAGMA busy_timeout=5000")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, check_same_thread=False)
        con.execute("PRAGMA busy_timeout=5000")  # ingest and predictor write different tables
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def upsert_reading(con: sqlite3.Connection, row: dict) -> bool:
    """Idempotent insert: a repeated (station, ts) only increments dup_count, values stay.

    Returns True when the row was new, False when it was a duplicate.
    """
    before = con.total_changes
    existing = con.execute(
        "SELECT 1 FROM readings WHERE station=? AND ts=?", (row["station"], row["ts"])
    ).fetchone()
    con.execute(_UPSERT_READING, [row.get(c) for c in READING_COLUMNS])
    assert con.total_changes > before
    return existing is None


def set_device_status(con: sqlite3.Connection, station: str, status: str, updated_at: str) -> None:
    con.execute(_UPSERT_STATUS, (station, status, updated_at))


def add_event(con: sqlite3.Connection, wall_ts: str, kind: str, payload: str) -> None:
    con.execute("INSERT INTO system_events VALUES (?, ?, ?)", (wall_ts, kind, payload))


PREDICTION_COLUMNS = [
    "station", "made_at_ts", "target_ts", "horizon", "yhat", "q10", "q90", "n_neighbors",
    "model_version",
]  # fmt: skip


def upsert_prediction(con: sqlite3.Connection, row: dict) -> None:
    """One prediction per (station, made_at_ts, horizon); a re-run replaces it."""
    cols = ", ".join(PREDICTION_COLUMNS)
    marks = ", ".join("?" for _ in PREDICTION_COLUMNS)
    con.execute(
        f"INSERT OR REPLACE INTO predictions({cols}) VALUES ({marks})",
        [row.get(c) for c in PREDICTION_COLUMNS],
    )
