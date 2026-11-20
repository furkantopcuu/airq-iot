"""Read-only HTTP API over the SQLite database (FastAPI). Control endpoints come later (spec 9).

Run: uvicorn airq.server.api:app  (AIRQ_DB / AIRQ_REPORTS override the default paths)
"Now" in this system is simulated time: windows are relative to a station's latest reading.
"""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from airq.server import db

HORIZONS = (1, 6, 24)


class Horizon(IntEnum):
    """Allowed forecast horizons in hours (query strings are coerced to these values)."""

    H1 = 1
    H6 = 6
    H24 = 24


class Health(BaseModel):
    status: str
    db: bool


class StationInfo(BaseModel):
    station: str
    status: str | None
    last_ts: str | None
    last_pm25: float | None
    quality_flags: list[str]
    active_warnings: int


class ReadingOut(BaseModel):
    ts: str
    pm25: float | None
    pm10: float | None
    quality_flags: list[str]
    seq: int | None


class ForecastOut(BaseModel):
    made_at_ts: str
    target_ts: str
    horizon: int
    yhat: float
    q10: float | None
    q90: float | None
    n_neighbors: int | None


class WarningOut(BaseModel):
    station: str
    made_at_ts: str
    horizon: int
    threshold: float
    yhat: float
    basis: str | None


def _latencies_ms(con: sqlite3.Connection) -> list[float]:
    """Wall-clock latency sent_at -> received_at (ms) of the latest 5000 readings."""
    out = []
    rows = con.execute(
        "SELECT sent_at, received_at FROM readings WHERE sent_at IS NOT NULL "
        "ORDER BY received_at DESC LIMIT 5000"
    )
    for r in rows:
        try:
            delta = datetime.fromisoformat(r["received_at"]) - datetime.fromisoformat(r["sent_at"])
        except (TypeError, ValueError):
            continue
        out.append(delta.total_seconds() * 1000)
    return out


def create_app(
    db_path: Path | str | None = None,
    reports_dir: Path | str | None = None,
    controller=None,
    truth=None,
    scenarios_dir: Path | str | None = None,
) -> FastAPI:
    """`controller` / `truth` can be injected (tests); by default the control endpoints connect to
    the broker named by AIRQ_BROKER on first use and read the recorded data lazily."""
    app = FastAPI(title="airq-iot API", version="0.2")
    paths = {"db": Path(db_path or os.environ.get("AIRQ_DB", "data/airq.db"))}
    paths["reports"] = Path(reports_dir or os.environ.get("AIRQ_REPORTS", "reports"))

    def get_con():
        if not paths["db"].exists():
            raise HTTPException(503, "database not available yet (is the ingest service running?)")
        con = db.connect(paths["db"], read_only=True)
        try:
            yield con
        finally:
            con.close()

    con_dep = Annotated[sqlite3.Connection, Depends(get_con)]

    def require_station(con: sqlite3.Connection, station: str) -> None:
        known = (
            con.execute("SELECT 1 FROM readings WHERE station=? LIMIT 1", (station,)).fetchone()
            or con.execute("SELECT 1 FROM device_status WHERE station=?", (station,)).fetchone()
        )
        if not known:
            raise HTTPException(404, f"unknown station '{station}'")

    @app.get("/health", response_model=Health)
    def health():
        return Health(status="ok", db=paths["db"].exists())

    @app.get("/stations", response_model=list[StationInfo])
    def stations(con: con_dep):
        names = {r[0] for r in con.execute("SELECT station FROM readings")} | {
            r[0] for r in con.execute("SELECT station FROM device_status")
        }
        out = []
        for st in sorted(names):
            status = con.execute(
                "SELECT status FROM device_status WHERE station=?", (st,)
            ).fetchone()
            last = con.execute(
                "SELECT ts, pm25, quality_flags FROM readings WHERE station=? "
                "ORDER BY ts DESC LIMIT 1",
                (st,),
            ).fetchone()
            n_warn = 0
            if last:
                since = (datetime.fromisoformat(last["ts"]) - timedelta(hours=24)).isoformat()
                n_warn = con.execute(
                    "SELECT COUNT(*) FROM warnings WHERE station=? AND made_at_ts>=?", (st, since)
                ).fetchone()[0]
            out.append(
                StationInfo(
                    station=st,
                    status=status["status"] if status else None,
                    last_ts=last["ts"] if last else None,
                    last_pm25=last["pm25"] if last else None,
                    quality_flags=json.loads(last["quality_flags"] or "[]") if last else [],
                    active_warnings=n_warn,
                )
            )
        return out

    @app.get("/readings/{station}", response_model=list[ReadingOut])
    def readings(station: str, con: con_dep, hours: Annotated[int, Query(ge=1, le=24 * 365)] = 72):
        require_station(con, station)
        rows = con.execute(
            "SELECT ts, pm25, pm10, quality_flags, seq FROM readings WHERE station=? "
            "ORDER BY ts DESC LIMIT ?",
            (station, hours),
        ).fetchall()
        return [
            ReadingOut(
                ts=r["ts"], pm25=r["pm25"], pm10=r["pm10"],
                quality_flags=json.loads(r["quality_flags"] or "[]"), seq=r["seq"],
            )
            for r in reversed(rows)
        ]  # fmt: skip

    @app.get("/forecast/{station}", response_model=list[ForecastOut])
    def forecast(
        station: str,
        con: con_dep,
        hours: Annotated[int, Query(ge=1, le=24 * 365)] = 72,
        horizon: Horizon | None = None,
    ):
        require_station(con, station)
        last = con.execute(
            "SELECT MAX(made_at_ts) FROM predictions WHERE station=?", (station,)
        ).fetchone()[0]
        if last is None:
            return []
        since = (datetime.fromisoformat(last) - timedelta(hours=hours)).isoformat()
        sql = (
            "SELECT made_at_ts, target_ts, horizon, yhat, q10, q90, n_neighbors FROM predictions "
            "WHERE station=? AND made_at_ts>?"
        )
        args: list = [station, since]
        if horizon is not None:
            sql += " AND horizon=?"
            args.append(int(horizon))
        rows = con.execute(sql + " ORDER BY made_at_ts, horizon", args).fetchall()
        return [ForecastOut(**dict(r)) for r in rows]

    @app.get("/warnings", response_model=list[WarningOut])
    def warnings(con: con_dep, station: str | None = None, since: str | None = None):
        if since is not None:
            try:
                datetime.fromisoformat(since)
            except ValueError as exc:
                raise HTTPException(422, "since must be an ISO timestamp") from exc
        sql, args = "SELECT station, made_at_ts, horizon, threshold, yhat, basis FROM warnings", []
        cond = []
        if station:
            cond.append("station=?")
            args.append(station)
        if since:
            cond.append("made_at_ts>=?")
            args.append(since)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        rows = con.execute(sql + " ORDER BY made_at_ts DESC, station", args).fetchall()
        return [WarningOut(**dict(r)) for r in rows]

    @app.get("/metrics")
    def metrics():
        """Offline result files (forecast_v*.json, edge_params.json ...) as one JSON object."""
        folder = paths["reports"] / "metrics"
        return {
            p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))
        }

    safe_name = re.compile(r"^[A-Za-z0-9_\-]+$")

    def reports_file(kind: str, name: str, suffix: str) -> Path:
        if not safe_name.match(name):  # no path separators or dots: no traversal
            raise HTTPException(422, "invalid name")
        path = paths["reports"] / kind / f"{name}{suffix}"
        if not path.is_file():
            raise HTTPException(404, f"{kind}/{name}{suffix} not found")
        return path

    @app.get("/tables")
    def tables():
        """Names of the experiment result tables (reports/tables/*.csv)."""
        folder = paths["reports"] / "tables"
        return sorted(p.stem for p in folder.glob("*.csv")) if folder.exists() else []

    @app.get("/tables/{name}")
    def table(name: str, limit: Annotated[int, Query(ge=1, le=20000)] = 5000):
        path = reports_file("tables", name, ".csv")
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [row for _, row in zip(range(limit), reader, strict=False)]
        return {"name": name, "columns": reader.fieldnames or [], "rows": rows}

    @app.get("/figures/{name}")
    def figure(name: str):
        return FileResponse(reports_file("figures", name, ".png"), media_type="image/png")

    @app.get("/system/stats")
    def system_stats(con: con_dep):
        n = con.execute("SELECT COUNT(*), COALESCE(SUM(dup_count),0) FROM readings").fetchone()
        unique, dups = n[0], n[1]
        lat = _latencies_ms(con)
        pct = {f"p{p}": round(float(np.percentile(lat, p)), 2) for p in (50, 95, 99)} if lat else {}
        edge = con.execute(
            "SELECT payload FROM system_events WHERE kind='edge_stats' "
            "ORDER BY wall_ts DESC LIMIT 1"
        ).fetchone()
        online_row = con.execute("SELECT COUNT(*) FROM device_status WHERE status='online'")
        online = online_row.fetchone()[0]
        return {
            "unique_messages": unique,
            "duplicates": dups,
            "duplicate_rate": (dups / unique) if unique else 0.0,
            "latency_ms": pct,
            "online_devices": online,
            "edge": json.loads(edge["payload"]) if edge else None,
        }

    from airq.server.control_api import ControlHub, register

    register(app, ControlHub(paths, controller, truth, scenarios_dir), get_con)
    return app


app = create_app()
