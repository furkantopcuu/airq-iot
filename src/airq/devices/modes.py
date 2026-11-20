"""Device intervention modes (spec 9.2): the pure logic behind the Senaryo Kontrol commands.

`InterventionSet` holds the interventions of ONE device and rewrites a recorded reading on its way
out. No MQTT in here, so every mode is unit-testable. Faults reuse
`perturb.inject.apply_perturbation` (the same function as RQ3b); only the hour-by-hour time
dimension is new.

Semantics (documented in docs/KARARLAR.md):
- An intervention starts at the first hour the device ticks AFTER the command arrived and lasts
  `duration_h` simulated hours (None = until reset). Several interventions compose in arrival order.
- ramp: `duration_h` is the length of the ramp. `target` mode moves linearly from the recorded value
  to the target (frac = k/duration_h at the k-th hour, then holds); `delta` mode adds frac*delta to
  the recorded value. After the ramp the value is HELD until reset (or `params.hold_h` more hours).
- coupled: a PM2.5 change also moves PM10 by (change * train-median PM10/PM2.5 ratio); it applies
  to manual / offset / scale / ramp (a sensor FAULT stays on its own channel).
- Values outside the physical range (PM 0..999) are refused at command time and clamped at apply
  time, unless the command says `allow_invalid` (the "faulty input test").
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from airq.iot.schemas import Command
from airq.perturb.inject import apply_perturbation

PHYSICAL_RANGE = {
    "pm25": (0.0, 999.0),
    "pm10": (0.0, 999.0),
}  # the dataset's valid range (edge rule a)
COUPLED_MODES = ("manual", "offset", "scale", "ramp")
HOUR = pd.Timedelta(hours=1)


def _isnum(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


@dataclass
class Intervention:
    cmd: Command
    start_ts: pd.Timestamp | None = None  # bound at the first apply()
    frozen: dict[str, float | None] = field(default_factory=dict)  # stuck: value before start

    def end_ts(self) -> pd.Timestamp | None:
        """Exclusive end of the active window (None = until reset)."""
        if self.start_ts is None:
            return None
        c = self.cmd
        if c.mode == "ramp":
            hold = c.params.get("hold_h")
            return None if hold is None else self.start_ts + (c.duration_h + hold) * HOUR
        return None if c.duration_h is None else self.start_ts + c.duration_h * HOUR

    def active(self, ts: pd.Timestamp) -> bool:
        if self.start_ts is None:
            return True  # not started yet: it starts with this tick
        end = self.end_ts()
        return ts >= self.start_ts and (end is None or ts < end)


class InterventionSet:
    """Interventions of one device. Thread-safe: commands arrive on the MQTT thread."""

    def __init__(self, coupled_ratio: float = 1.0, sigma: dict[str, float] | None = None):
        self.coupled_ratio = coupled_ratio  # train median PM10/PM2.5
        self.sigma = sigma or {}  # train robust sigma per variable (spike size)
        self._items: list[Intervention] = []
        self._last_out: dict[str, float] = {}  # last value this device emitted, per variable
        self._lock = threading.Lock()

    # --- commands --------------------------------------------------------------------------
    def validate(self, cmd: Command) -> str | None:
        """Return an error text when the command must be refused, else None."""
        p = cmd.params
        if cmd.mode == "perturb" and p["type"] == "spike":
            missing = [v for v in cmd.variables if self.sigma.get(v) is None]
            if missing:
                return f"no train sigma available for {missing}; cannot size the spike"
        if cmd.allow_invalid or cmd.mode in ("replay", "offline"):
            return None
        for var in cmd.variables:
            lo_hi = PHYSICAL_RANGE.get(var)
            if lo_hi is None:
                continue
            last = self._last_out.get(var)
            end = None
            if cmd.mode == "manual":
                end = p["value"]
            elif cmd.mode == "ramp":
                end = (
                    p["target"] if "target" in p else (None if last is None else last + p["delta"])
                )
            elif cmd.mode == "offset" and last is not None:
                end = last + p["delta"]
            elif cmd.mode == "scale" and last is not None:
                end = last * p["factor"]
            if end is not None and not lo_hi[0] <= end <= lo_hi[1]:
                return (
                    f"{var} would become {end:g}, outside the physical range "
                    f"[{lo_hi[0]:g}, {lo_hi[1]:g}]; tick allow_invalid to test faulty input"
                )
        return None

    def add(self, cmd: Command) -> str | None:
        """Register a command; returns an error text (and registers nothing) when refused."""
        with self._lock:
            err = self.validate(cmd)
            if err:
                return err
            if cmd.mode == "replay":  # back to the recorded data for these variables
                self._clear(set(cmd.variables))
                return None
            self._items.append(
                Intervention(cmd, frozen={v: self._last_out.get(v) for v in cmd.variables})
            )
            return None

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def _clear(self, variables: set[str]) -> None:
        kept = []
        for iv in self._items:
            if iv.cmd.mode == "offline":
                continue  # replay brings an offline device back
            left = [v for v in iv.cmd.variables if v not in variables]
            if left:
                kept.append(
                    Intervention(
                        iv.cmd.model_copy(update={"variables": left}), iv.start_ts, iv.frozen
                    )
                )
        self._items = kept

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def describe(self) -> list[dict]:
        with self._lock:
            return [
                {"cmd_id": i.cmd.cmd_id, "mode": i.cmd.mode, "variables": i.cmd.variables,
                 "start_ts": None if i.start_ts is None else i.start_ts.isoformat(),
                 "label": i.cmd.label}
                for i in self._items
            ]  # fmt: skip

    # --- per-hour application --------------------------------------------------------------
    def is_offline(self, ts: pd.Timestamp) -> bool:
        with self._lock:
            self._expire(ts)
            for iv in self._items:
                if iv.cmd.mode == "offline":
                    if iv.start_ts is None:
                        iv.start_ts = ts
                    if iv.active(ts):
                        return True
            return False

    def apply(self, ts: pd.Timestamp, values: dict[str, float | None]) -> dict[str, float | None]:
        """Return `values` (the recorded reading) with every active intervention applied."""
        ts = pd.Timestamp(ts)
        with self._lock:
            self._expire(ts)
            out = dict(values)
            for iv in self._items:
                if iv.cmd.mode == "offline":
                    continue
                if iv.start_ts is None:
                    iv.start_ts = ts
                if iv.active(ts):
                    self._apply_one(iv, ts, out)
            for var, lim in PHYSICAL_RANGE.items():
                if _isnum(out.get(var)) and not self._allows_invalid(var):
                    out[var] = float(min(max(out[var], lim[0]), lim[1]))
            for var, x in out.items():
                if _isnum(x):
                    self._last_out[var] = float(x)
            return out

    def _allows_invalid(self, var: str) -> bool:
        return any(i.cmd.allow_invalid and var in i.cmd.variables for i in self._items)

    def _expire(self, ts: pd.Timestamp) -> None:
        self._items = [
            i for i in self._items
            if i.start_ts is None or (i.end_ts() is None or ts < i.end_ts())
        ]  # fmt: skip

    def _apply_one(self, iv: Intervention, ts, out: dict) -> None:
        c, p = iv.cmd, iv.cmd.params
        k = int((ts - iv.start_ts) / HOUR) + 1  # hours since the start, 1 = first affected hour
        for var in c.variables:
            cur = out.get(var)
            new = cur
            if c.mode == "manual":
                new = float(p["value"])
            elif c.mode == "offset" and _isnum(cur):
                new = cur + p["delta"]
            elif c.mode == "scale" and _isnum(cur):
                new = cur * p["factor"]
            elif c.mode == "ramp" and _isnum(cur):
                frac = min(k / c.duration_h, 1.0)
                new = (
                    (1 - frac) * cur + frac * p["target"]
                    if "target" in p
                    else cur + frac * p["delta"]
                )
            elif c.mode == "perturb":
                new = self._perturb(iv, var, cur, k)
            out[var] = new
            coupled = c.coupled and c.mode in COUPLED_MODES and "pm10" not in c.variables
            if (
                var == "pm25"
                and coupled
                and _isnum(new)
                and _isnum(cur)
                and _isnum(out.get("pm10"))
            ):
                out["pm10"] = out["pm10"] + (new - cur) * self.coupled_ratio

    def _perturb(self, iv: Intervention, var: str, x, k: int):
        p = iv.cmd.params
        if not _isnum(x) and p["type"] != "dropout":
            return x  # a missing reading cannot be spiked or frozen
        frozen = iv.frozen.get(var)
        arr = np.array([np.nan if frozen is None else frozen, np.nan if x is None else x], float)
        apply_perturbation(
            arr, 1, 1, p["type"], float(p.get("severity", 0.0)), float(self.sigma.get(var, 0.0))
        )
        return None if np.isnan(arr[1]) else float(arr[1])
