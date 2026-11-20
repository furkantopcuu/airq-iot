"""Control endpoints of the API (spec 8.6 / 9): commands go out over MQTT, acks come back.

POST /control/device|fleet|network|edge   one command, answered with the devices' acks
POST /control/scenario/{name}             play a scenario on the running stack (simulated time)
POST /control/reset                       drop every intervention, network emulation, edge filter
GET  /control/active | /control/scorecard | /control/scenarios | /control/scenario

No authentication (localhost only, spec 9.7): a real deployment needs MQTT ACLs + TLS.
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import Body, Depends, FastAPI, HTTPException

from airq.iot.schemas import ALL_TARGET
from airq.scenarios.player import PlayerThread, ScenarioPlayer
from airq.scenarios.spec import Scenario, build_message, load_all
from airq.server import db
from airq.server.control import Controller
from airq.server.scorecard import intervention_rows, scorecard
from airq.server.truth import Truth

ACK_TIMEOUT_S = 3.0
DEVICE_MODES_ACTIVE = ("manual", "offset", "scale", "ramp", "perturb", "offline")


def active_state(rows: list[dict], sim_now: str | None) -> dict:
    """Fold the command log into what is in force now (pure; see tests).

    A fleet `reset` drops interventions and network emulation; the edge filter and the fleet
    speed / pause state are NOT undone by it (the reset endpoint switches the filter on itself).
    """
    ok = [r for r in rows if r["acked"]]
    reset_at = max((r["rowid"] for r in ok if r["station"] == "fleet" and r["mode"] == "reset"),
                   default=0)  # fmt: skip
    interventions: list[dict] = []
    network: dict[str, dict] = {}
    edge, fleet = "on", {"paused": False, "speedup": None}
    for r in ok:
        params = json.loads(r["params"] or "{}")
        mode, after_reset = r["mode"], r["rowid"] > reset_at
        if mode == "filter":
            edge = params.get("filter", edge)
        elif r["station"] == "fleet":
            if mode == "pause":
                fleet["paused"] = True
            elif mode == "resume":
                fleet["paused"] = False
            elif mode == "speedup":
                fleet["speedup"] = params.get("value")
        elif not after_reset:
            continue
        elif mode in DEVICE_MODES_ACTIVE:
            expired = r["end_ts"] is not None and sim_now is not None and r["end_ts"] <= sim_now
            if r["start_ts"] is None or expired:
                continue
            interventions.append(
                {
                    "cmd_id": r["cmd_id"],
                    "station": r["station"],
                    "mode": mode,
                    "label": r["label"],
                    "variables": json.loads(r["variables"] or "[]"),
                    "start_ts": r["start_ts"],
                    "end_ts": r["end_ts"],
                    "rowid": r["rowid"],
                }
            )
        elif mode == "replay":  # clears the named variables on that station (or all)
            gone = set(json.loads(r["variables"] or "[]"))
            targets = (ALL_TARGET, r["station"])
            interventions = [
                i
                for i in interventions
                if not (
                    (r["station"] == ALL_TARGET or i["station"] in targets)
                    and (gone & set(i["variables"]) or i["mode"] == "offline")
                )
            ]
        elif mode == "net":
            if not params.get("reset"):
                network[r["station"]] = {k: v for k, v in params.items() if k != "reset"}
            elif r["station"] == ALL_TARGET:
                network = {}
            else:
                network.pop(r["station"], None)
    return {"interventions": interventions, "network": network, "edge_filter": edge, "fleet": fleet}


class ControlHub:
    """Shared state of the control endpoints: MQTT controller, truth data, running scenario."""

    def __init__(
        self,
        paths: dict[str, Path],
        controller: Controller | None = None,
        truth: Truth | None = None,
        scenarios_dir: Path | str | None = None,
    ):
        self.paths = paths
        self._controller = controller
        self._truth = truth
        self._truth_tried = truth is not None
        self.scenarios_dir = Path(
            scenarios_dir or os.environ.get("AIRQ_SCENARIOS", "configs/scenarios")
        )
        self._lock = threading.Lock()
        self.player: ScenarioPlayer | None = None
        self.thread: PlayerThread | None = None

    def controller(self) -> Controller:
        with self._lock:
            if self._controller is None:
                host, _, port = os.environ.get("AIRQ_BROKER", "127.0.0.1:1883").rpartition(":")
                ctl = Controller(host or "127.0.0.1", int(port), client_id="api-control")
                try:
                    ctl.start()
                except Exception as exc:  # noqa: BLE001 - reported to the caller as 503
                    raise HTTPException(503, f"MQTT broker not reachable: {exc}") from exc
                self._controller = ctl
            return self._controller

    def truth(self) -> Truth | None:
        with self._lock:
            if not self._truth_tried:
                self._truth_tried = True
                try:
                    from airq.config import load_config

                    self._truth = Truth.from_cfg(load_config())
                except Exception:  # noqa: BLE001 - no recorded data: scorecard falls back
                    self._truth = None
            return self._truth

    def scenarios(self) -> dict[str, Scenario]:
        return load_all(self.scenarios_dir) if self.scenarios_dir.exists() else {}

    def stop_player(self) -> None:
        if self.thread is not None:
            self.thread.stop_flag.set()


def _sim_now(con: sqlite3.Connection) -> str | None:
    return con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]


def register(app: FastAPI, hub: ControlHub, get_con) -> None:
    con_dep = Annotated[sqlite3.Connection, Depends(get_con)]
    body_t = Annotated[dict[str, Any], Body()]

    def send(msg, expect: int = 1) -> dict:
        ctl = hub.controller()
        ctl.send(msg)
        acks = ctl.wait_acks(msg.cmd_id, expect, ACK_TIMEOUT_S)
        if not acks:
            raise HTTPException(504, "no ack: is the fleet running with --control?")
        errors = [a.error for a in acks if not a.ok]
        if len(acks) < expect:
            errors.append(f"only {len(acks)} of {expect} devices answered")
        return {"cmd_id": msg.cmd_id, "ok": not errors, "errors": errors,
                "acks": [a.model_dump(mode="json") for a in acks]}  # fmt: skip

    def build(kind: str, body: dict) -> Any:
        try:
            return build_message({**body, "kind": kind})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def online_count(con) -> int:
        n = con.execute("SELECT COUNT(*) FROM device_status WHERE status='online'").fetchone()[0]
        return max(int(n), 1)

    @app.post("/control/device")
    def control_device(body: body_t, con: con_dep):
        msg = build("device", body)
        expect = online_count(con) if msg.target == ALL_TARGET else 1
        return send(msg, expect)

    @app.post("/control/fleet")
    def control_fleet(body: body_t):
        return send(build("fleet", body))

    @app.post("/control/network")
    def control_network(body: body_t):
        return send(build("network", body))

    @app.post("/control/edge")
    def control_edge(body: body_t):
        return send(build("edge", body))

    @app.post("/control/reset")
    def control_reset():
        hub.stop_player()
        out = {"fleet": send(build("fleet", {"action": "reset", "label": "reset"}))}
        try:
            out["edge"] = send(build("edge", {"filter": "on", "label": "reset"}))
        except HTTPException as exc:
            out["edge"] = {"ok": False, "errors": [exc.detail]}
        out["ok"] = all(v.get("ok") for v in out.values() if isinstance(v, dict))
        return out

    @app.get("/control/scenarios")
    def list_scenarios():
        return [
            {"name": s.name, "description": s.description, "steps": len(s.steps),
             "start": s.start, "duration_h": s.duration_h, "warmup_h": s.warmup_h}
            for s in hub.scenarios().values()
        ]  # fmt: skip

    @app.post("/control/scenario/{name}")
    def run_scenario(name: str, con: con_dep):
        scenarios = hub.scenarios()
        if name not in scenarios:
            raise HTTPException(404, f"unknown scenario '{name}'")
        if hub.player is not None and not hub.player.done and hub.thread and hub.thread.is_alive():
            raise HTTPException(409, f"scenario '{hub.player.scenario.name}' is still running")
        stations = [r[0] for r in con.execute("SELECT station FROM device_status ORDER BY 1")]
        now = _sim_now(con)
        hub.player = ScenarioPlayer(
            scenarios[name], hub.controller(), stations or ["x"],
            None if now is None else pd.Timestamp(now),
        )  # fmt: skip

        def clock():
            c = db.connect(hub.paths["db"], read_only=True)
            try:
                v = _sim_now(c)
            finally:
                c.close()
            return None if v is None else pd.Timestamp(v)

        hub.thread = PlayerThread(hub.player, clock)
        hub.thread.start()
        return hub.player.status()

    @app.get("/control/scenario")
    def scenario_status():
        if hub.player is None:
            return {"name": None}
        return hub.player.status()

    @app.get("/control/active")
    def active(con: con_dep):
        state = active_state(intervention_rows(con), _sim_now(con))
        state["sim_now"] = _sim_now(con)
        state["scenario"] = hub.player.status() if hub.player else None
        return state

    @app.get("/control/scorecard")
    def get_scorecard(con: con_dep):
        truth = hub.truth()
        marks = list(hub.player.marks) if hub.player else []
        rows = scorecard(con, truth, marks)
        for r in rows:
            r["reference"] = "recorded data replay" if truth is not None else "database (observed)"
        return {"reference": rows[0]["reference"] if rows else None, "rows": rows}
