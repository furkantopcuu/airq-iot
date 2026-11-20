"""Live scorecard (spec 9.6): did the system warn, was the warning right, how early, how wrong.

An `Item` is one intervention (a device command) or one bookmark (`mark`). For each item the
scorecard reads the run database and compares against a reference series (server/truth.py):
fault scenarios (spike/stuck/dropout) are judged against the CLEAN recorded value, everything else
against what the device really emitted. All numbers come from the database, none are invented.
Warnings use the 150 ug/m3 threshold (the haze level); a warning is "matched" when its target hour
(made_at + horizon) really exceeded it (horizon-matched, as in the RQ2 evaluation).
An ONSET is an exceedance that follows at least ONSET_GAP_H hours below the threshold; every
onset inside the window is scored, per station. A warning counts towards an onset's lead time
only when its TARGET hour lies inside that onset's own exceedance episode. Scoring version 2
(this file); version 1 - the first exceedance in the window, any matching warning - was wrong
for windows that open inside a running haze and is kept in the stored run files for audit.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from airq.devices.modes import HOUR
from airq.iot.schemas import MODES
from airq.server.truth import Truth

THRESHOLD = 150.0
ONSET_GAP_H = 6  # an onset follows >= 6 h below the threshold (episodes.merge_gap_h)
SCORING_VERSION = 2
DEFAULT_WINDOW_H = 24.0
FAULT_MODES = ("perturb",)


@dataclass
class Item:
    label: str
    stations: list[str] | None  # None = all stations
    t0: pd.Timestamp
    t1: pd.Timestamp | None  # None = default window
    kind: str  # "fault" | "world" | "mark"
    mode: str
    edge_filter: str = "on"
    cmd_id: str | None = None


def intervention_rows(con: sqlite3.Connection) -> list[dict]:
    rows = []
    for r in con.execute("SELECT rowid AS rowid, * FROM interventions ORDER BY rowid"):
        rows.append(dict(r))
    return rows


def _edge_before(rows: list[dict], rowid: int) -> str:
    state = "on"
    for r in rows:
        if r["rowid"] >= rowid:
            break
        if r["station"] == "edge" and r["mode"] == "filter" and r.get("acked"):
            state = json.loads(r["params"] or "{}").get("filter", state)
    return state


def items_from_rows(rows: list[dict], marks: list[dict] | None = None) -> list[Item]:
    """Accepted device commands + marks ({label, target, t0, duration_h, rowid?})."""
    items = []
    for r in rows:
        if r["mode"] not in MODES or r["mode"] == "replay":
            continue
        if not r.get("acked") or r.get("start_ts") is None:
            continue
        end = pd.Timestamp(r["end_ts"]) if r.get("end_ts") else None
        items.append(
            Item(
                label=r.get("label") or (r["cmd_id"] or "")[:8],
                stations=None if r["station"] == "all" else [r["station"]],
                t0=pd.Timestamp(r["start_ts"]),
                t1=end,
                kind="fault" if r["mode"] in FAULT_MODES else "world",
                mode=r["mode"],
                edge_filter=_edge_before(rows, r["rowid"]),
                cmd_id=r["cmd_id"],
            )
        )
    last_rowid = rows[-1]["rowid"] + 1 if rows else 0
    for m in marks or []:
        t0 = pd.Timestamp(m["t0"])
        dur = m.get("duration_h")
        stations = None if m.get("target", "all") == "all" else [m["target"]]
        items.append(
            Item(
                label=m["label"],
                stations=stations,
                t0=t0,
                t1=None if dur is None else t0 + dur * HOUR,
                kind="mark",
                mode="mark",
                edge_filter=m.get("edge_filter") or _edge_before(rows, m.get("rowid", last_rowid)),
            )
        )
    return items


def _num(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


def score_item(
    con: sqlite3.Connection,
    item: Item,
    rows: list[dict],
    truth: Truth | None = None,
    all_stations: list[str] | None = None,
) -> dict:
    stations = (
        item.stations
        or all_stations
        or [r[0] for r in con.execute("SELECT DISTINCT station FROM readings")]
    )
    t0 = item.t0
    win_end = item.t1 or t0 + DEFAULT_WINDOW_H * HOUR
    hi = win_end + 36 * HOUR
    lo = t0 - ONSET_GAP_H * HOUR  # context for judging whether the first hours are an onset
    ref: dict[str, pd.Series] = {}
    for st in stations:
        if truth is not None and st in truth.series:
            if item.kind == "fault":
                ref[st] = truth.clean(st, lo, hi)
            else:
                ref[st] = truth.emitted(st, rows, lo, hi)
        else:  # no recorded data available: fall back to what the database observed
            ref[st] = _observed(con, st, lo, hi)
    ph = ",".join("?" for _ in stations)
    preds = pd.read_sql_query(
        f"SELECT station, made_at_ts, target_ts, horizon, yhat, n_neighbors FROM predictions "
        f"WHERE station IN ({ph}) AND made_at_ts >= ? AND made_at_ts <= ?",
        con,
        params=[*stations, _iso(t0), _iso(win_end)],
    )
    warns = pd.read_sql_query(
        f"SELECT station, made_at_ts, horizon, threshold FROM warnings "
        f"WHERE station IN ({ph}) AND made_at_ts >= ? AND made_at_ts <= ? AND threshold = ?",
        con,
        params=[*stations, _iso(t0), _iso(win_end), THRESHOLD],
    )

    def truth_at(st: str, ts) -> float:
        s = ref.get(st)
        v = s.get(pd.Timestamp(ts)) if s is not None else None
        return np.nan if v is None else v

    out: dict = {
        "label": item.label,
        "kind": item.kind,
        "mode": item.mode,
        "edge_filter": item.edge_filter,
        "stations": ",".join(stations) if item.stations else "all",
        "t0": _iso(t0),
        "t1": _iso(win_end),
        "n_forecasts": int(len(preds)),
    }
    first6 = preds[pd.to_datetime(preds["made_at_ts"]) < t0 + 6 * HOUR]
    for h in (1, 6):
        sub = first6[first6["horizon"] == h]
        err = [
            abs(r.yhat - truth_at(r.station, r.target_ts))
            for r in sub.itertuples()
            if not np.isnan(truth_at(r.station, r.target_ts))
        ]
        out[f"mae_next_6h_h{h}"] = _num(np.mean(err)) if err else None
    h6 = preds[preds["horizon"] == 6]
    out["peak_forecast_h6"] = _num(h6["yhat"].max()) if len(h6) else None
    out["min_n_neighbors"] = _num(preds["n_neighbors"].min()) if len(preds) else None
    matched, leads, found = [], [], []
    for st in stations:
        ws = warns[warns["station"] == st]
        hits = [  # (made_at, target) of warnings whose target hour really exceeded
            (pd.Timestamp(r.made_at_ts), pd.Timestamp(r.made_at_ts) + r.horizon * HOUR)
            for r in ws.itertuples()
            if truth_at(st, pd.Timestamp(r.made_at_ts) + r.horizon * HOUR) >= THRESHOLD
        ]
        matched.extend(made for made, _ in hits)
        s = ref.get(st)
        for onset in [o for o in (onsets(s, t0) if s is not None else []) if o <= win_end]:
            found.append(onset)
            end = episode_end(s, onset)
            early = [made for made, target in hits if made <= onset and onset <= target <= end]
            if early:
                leads.append((onset - min(early)) / HOUR)
    out["warned"] = bool(len(warns))
    out["matched"] = bool(matched)
    out["lead_time_h"] = _num(float(np.median(leads))) if leads else None
    out["n_onsets"] = len(found)  # onsets over all stations in the window
    out["n_onsets_warned_ahead"] = sum(lead > 0 for lead in leads)  # caught BEFORE the onset hour
    out["first_onset"] = _iso(min(found)) if found else None
    out["scoring_version"] = SCORING_VERSION
    out.update(_delivery(con, stations, t0, win_end))
    return out


def onsets(s: pd.Series, t0, threshold: float = THRESHOLD, gap_h: int = ONSET_GAP_H) -> list:
    """Every onset at/after t0: an hour >= `threshold` preceded by `gap_h` hours below it.

    `s` must reach back `gap_h` hours before t0 so the first hour can be judged; a candidate whose
    preceding hours are not all in the series is skipped (unknown history). NaN counts as below.
    After an onset the search resumes once its episode (merged over short dips) is over.
    """
    t0, found, resume = pd.Timestamp(t0), [], None
    for ts in s[(s.index >= t0) & (s >= threshold)].index:
        if resume is not None and ts <= resume:
            continue
        before = s[(s.index >= ts - gap_h * HOUR) & (s.index < ts)]
        if len(before) == gap_h and not (before >= threshold).any():
            found.append(ts)
            resume = episode_end(s, ts, threshold, gap_h)
    return found


def first_onset(s: pd.Series, t0, threshold: float = THRESHOLD, gap_h: int = ONSET_GAP_H):
    found = onsets(s, t0, threshold, gap_h)
    return found[0] if found else None


def episode_end(s: pd.Series, onset, threshold: float = THRESHOLD, gap_h: int = ONSET_GAP_H):
    """Last exceedance hour of the episode that starts at `onset` (merged over short dips)."""
    after = s[s.index >= onset]
    last, below = onset, 0
    for ts, v in after.items():
        if v >= threshold:
            last, below = ts, 0
        else:
            below += 1
            if below >= gap_h:
                break
    return last


def _observed(con, station: str, lo, hi) -> pd.Series:
    df = pd.read_sql_query(
        "SELECT ts, pm25 FROM readings WHERE station=? AND ts >= ? AND ts <= ?",
        con,
        params=[station, _iso(lo), _iso(hi)],
    )
    return pd.Series(df["pm25"].to_numpy(float), index=pd.to_datetime(df["ts"]))


def _delivery(con, stations: list[str], t0, t1) -> dict:
    """Share of the sent seq numbers that arrived, and wall-clock latency p95 (ms)."""
    got = sent = 0
    lat: list[float] = []
    for st in stations:
        df = pd.read_sql_query(
            "SELECT seq, sent_at, received_at FROM readings "
            "WHERE station=? AND ts >= ? AND ts <= ? AND seq IS NOT NULL",
            con,
            params=[st, _iso(t0), _iso(t1)],
        )
        if df.empty:
            continue
        got += len(df)
        sent += int(df["seq"].max() - df["seq"].min() + 1)
        d = pd.to_datetime(df["received_at"]) - pd.to_datetime(df["sent_at"])
        lat.extend(d.dt.total_seconds().mul(1000).tolist())
    return {
        "delivery_ratio": _num(got / sent) if sent else None,
        "latency_p95_ms": _num(np.percentile(lat, 95)) if lat else None,
    }


def scorecard(
    con: sqlite3.Connection,
    truth: Truth | None = None,
    marks: list[dict] | None = None,
    all_stations: list[str] | None = None,
) -> list[dict]:
    rows = intervention_rows(con)
    return [score_item(con, it, rows, truth, all_stations) for it in items_from_rows(rows, marks)]
