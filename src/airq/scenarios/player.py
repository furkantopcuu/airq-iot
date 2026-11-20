"""Plays a scenario's steps against a running stack, driven by SIMULATED time.

`tick(sim_now)` fires every step whose time (zero + at_h) has been reached, once. The caller feeds
it the simulated clock (the newest reading in the database), so pause / speedup / jump just work.
Each fired step waits for its acks, so an intervention is in force before the next hour is played.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pandas as pd

from airq.devices.modes import HOUR
from airq.iot.schemas import ALL_TARGET, Command
from airq.scenarios.spec import Mark, Scenario, build_message, label_of
from airq.server.control import Controller


class ScenarioPlayer:
    def __init__(
        self,
        scenario: Scenario,
        controller: Controller,
        stations: list[str],
        zero_ts: pd.Timestamp | None = None,
        ack_timeout_s: float = 5.0,
    ):
        self.scenario, self.controller, self.stations = scenario, controller, stations
        self.zero_ts = None if zero_ts is None else pd.Timestamp(zero_ts)
        self.ack_timeout_s = ack_timeout_s
        self._fired: set[int] = set()
        self.log: list[dict] = []
        self.marks: list[dict] = []
        self.edge_filter = "on"  # what the edge is believed to be doing (for mark rows)
        self._lock = threading.Lock()

    @property
    def done(self) -> bool:
        return len(self._fired) == len(self.scenario.steps)

    def tick(self, sim_now: pd.Timestamp) -> list[dict]:
        """Fire due steps; returns the log entries produced by this call."""
        sim_now = pd.Timestamp(sim_now)
        with self._lock:
            if self.zero_ts is None:
                self.zero_ts = sim_now
            fired = []
            for i, step in enumerate(self.scenario.steps):
                if i in self._fired or sim_now < self.zero_ts + step.at_h * HOUR:
                    continue
                self._fired.add(i)
                fired.append(self._fire(i, step, sim_now))
            return fired

    def _fire(self, i: int, step, sim_now: pd.Timestamp) -> dict:
        msg = build_message(step.command)
        nominal = self.zero_ts + step.at_h * HOUR
        entry = {
            "step": i,
            "at_h": step.at_h,
            "label": label_of(msg),
            "sim_ts": nominal.isoformat(),
            "kind": type(msg).__name__,
        }
        if isinstance(msg, Mark):
            self.marks.append(
                {
                    "label": msg.label,
                    "target": msg.target,
                    "t0": nominal,
                    "duration_h": msg.duration_h,
                    "edge_filter": self.edge_filter,
                }  # fmt: skip
            )
            entry.update(ok=True, cmd_id=None, errors=[])
        else:
            expect = (
                len(self.stations)
                if getattr(msg, "target", None) == ALL_TARGET and isinstance(msg, Command)
                else 1
            )
            self.controller.send(msg)
            acks = self.controller.wait_acks(msg.cmd_id, expect, self.ack_timeout_s)
            errors = [a.error for a in acks if not a.ok]
            if len(acks) < expect:
                errors.append(f"only {len(acks)} of {expect} acks arrived")
            entry.update(ok=not errors, cmd_id=msg.cmd_id, errors=errors)
            if hasattr(msg, "filter") and entry["ok"]:
                self.edge_filter = msg.filter
        self.log.append(entry)
        return entry

    def status(self) -> dict:
        with self._lock:
            return {
                "name": self.scenario.name,
                "description": self.scenario.description,
                "zero_ts": None if self.zero_ts is None else self.zero_ts.isoformat(),
                "steps_total": len(self.scenario.steps),
                "steps_fired": len(self._fired),
                "done": self.done,
                "log": list(self.log),
            }


class PlayerThread(threading.Thread):
    """Polls a simulated clock and feeds the player until it is done or stopped."""

    def __init__(
        self, player: ScenarioPlayer, clock: Callable[[], pd.Timestamp | None], poll_s: float = 0.2
    ):
        super().__init__(name=f"scenario-{player.scenario.name}", daemon=True)
        self.player, self.clock, self.poll_s = player, clock, poll_s
        self.stop_flag = threading.Event()

    def run(self) -> None:
        while not self.stop_flag.is_set() and not self.player.done:
            now = self.clock()
            if now is not None:
                self.player.tick(now)
            time.sleep(self.poll_s)


def marks_for(scenario: Scenario, zero_ts: pd.Timestamp) -> list[dict]:
    """The bookmarks a finished run of `scenario` placed (for re-scoring a stored run)."""
    marks, edge = [], "on"
    for step in scenario.steps:
        msg = build_message(step.command)
        if isinstance(msg, Mark):
            marks.append(
                {
                    "label": msg.label,
                    "target": msg.target,
                    "t0": pd.Timestamp(zero_ts) + step.at_h * HOUR,
                    "duration_h": msg.duration_h,
                    "edge_filter": edge,
                }
            )
        elif hasattr(msg, "filter"):
            edge = msg.filter
    return marks
