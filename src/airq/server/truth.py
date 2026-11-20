"""Reference series for the scorecard: what a sensor WOULD have / DID report (spec 9.6).

The devices replay recorded data, so both are computable offline:
- `clean`   = the recorded PM2.5 (what an intact sensor reports): the reference for FAULT scenarios;
- `emitted` = the recorded series with the logged commands replayed through the same mode engine
              the devices use (devices/modes.py): the reference when the intervention changes the
              WORLD (ramp, offset, ...) and for what really went out on the wire.
The edge filter can null an emitted value in the database; `emitted` is therefore the better truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from airq.devices.modes import HOUR, InterventionSet
from airq.iot.schemas import MODES, Command


@dataclass(frozen=True)
class LoggedEvent:
    effective: pd.Timestamp  # first tick the event acts on
    order: int  # database insertion order (rowid)
    kind: str  # "add" | "reset"
    cmd: Command | None = None


def command_from_row(row: dict) -> Command | None:
    """Rebuild a device command from an `interventions` row (None for fleet/net/edge rows)."""
    if row["mode"] not in MODES:
        return None
    params = json.loads(row["params"] or "{}")
    extra = {k: params.pop(k, None) for k in ("duration_h", "coupled", "allow_invalid")}
    return Command(
        cmd_id=row["cmd_id"], issued_at="2000-01-01T00:00:00", target=row["station"],
        variables=json.loads(row["variables"] or '["pm25"]'), mode=row["mode"], params=params,
        duration_h=extra["duration_h"], coupled=bool(extra["coupled"]),
        allow_invalid=bool(extra["allow_invalid"]), label=row.get("label"),
    )  # fmt: skip


def events_for(station: str, rows: list[dict]) -> list[LoggedEvent]:
    """Accepted commands (ok acks) and fleet resets that acted on `station`, in effect order."""
    out = []
    for r in rows:
        if not r.get("acked") or r.get("start_ts") is None:
            continue
        start = pd.Timestamp(r["start_ts"])
        if r["station"] == "fleet" and r["mode"] == "reset":
            out.append(LoggedEvent(start + HOUR, r["rowid"], "reset"))
            continue
        cmd = command_from_row(r)
        if cmd is not None and cmd.target in (station, "all"):
            out.append(LoggedEvent(start, r["rowid"], "add", cmd))
    return sorted(out, key=lambda e: (e.effective, e.order))


class Truth:
    """Recorded series per station + the train-only calibration the devices were given."""

    def __init__(self, raw: pd.DataFrame, calibration: dict):
        self.ratio = calibration.get("ratio", 1.0)
        self.sigma = calibration.get("sigma", {})
        cols = ["pm25", "pm10"]
        self.series = {
            st: g.drop_duplicates("ts").set_index("ts").sort_index()[cols]
            for st, g in raw.groupby("station")
        }

    @classmethod
    def from_cfg(cls, cfg: dict) -> Truth:
        from airq.data.load import load_raw
        from airq.devices.fleet import train_calibration
        from airq.env import resolve_paths

        hits = sorted((resolve_paths(cfg["paths"])["raw"] / "beijing").rglob("PRSA_Data_*.csv"))
        if not hits:
            raise FileNotFoundError("raw data not found; run scripts.download_data first")
        raw = load_raw(hits[0].parent)
        return cls(raw, train_calibration(raw, cfg))

    def stations(self) -> list[str]:
        return list(self.series)

    def clean(self, station: str, lo, hi) -> pd.Series:
        s = self.series[station]["pm25"]
        return s[(s.index >= pd.Timestamp(lo)) & (s.index <= pd.Timestamp(hi))]

    def emitted(self, station: str, rows: list[dict], lo, hi) -> pd.Series:
        """PM2.5 the device put on the wire (NaN while offline), replaying the command log."""
        lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
        events = events_for(station, rows)
        if events:  # stuck / ramps need the hours before the first command
            lo = min(lo, events[0].effective - 48 * HOUR)
        base = self.series[station]
        base = base[(base.index >= lo) & (base.index <= hi)]
        iv = InterventionSet(self.ratio, self.sigma.get(station))
        out, i = {}, 0
        for ts, row in base.iterrows():
            while i < len(events) and events[i].effective <= ts:
                if events[i].kind == "reset":
                    iv.reset()
                else:
                    iv.add(events[i].cmd)
                i += 1
            if iv.is_offline(ts):
                out[ts] = np.nan
                continue
            vals = {k: (None if pd.isna(v) else float(v)) for k, v in row.items()}
            v = iv.apply(ts, vals)["pm25"]
            out[ts] = np.nan if v is None else v
        return pd.Series(out, dtype=float)
