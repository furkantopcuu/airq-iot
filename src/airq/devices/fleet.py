"""Fleet of virtual sensors sharing one simulated clock.

python -m airq.devices.fleet --start 2016-03-01 --end 2016-03-15 --speedup 3600 \
    --stations all --seed 0 --broker 127.0.0.1:1883
speedup=3600 -> 1 wall second = 1 simulated hour; speedup=0 -> as fast as possible.
"""

from __future__ import annotations

import argparse
import threading
import time

import pandas as pd

from airq.config import load_config
from airq.data.load import load_raw
from airq.devices.netem import DelayedRunner, NetEm, NetParams
from airq.devices.virtual_sensor import VirtualSensor
from airq.env import resolve_paths
from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import ALL_TARGET, MEASUREMENTS, Ack, FleetControl, NetControl, parse_command
from airq.perturb.inject import robust_sigma


def train_calibration(raw: pd.DataFrame, cfg: dict) -> dict:
    """Per-station spike sigma and the PM10/PM2.5 ratio, fitted on TRAIN only (no leakage)."""
    hi = pd.Timestamp(cfg["split"]["train"][1])
    tr = raw[raw["ts"] <= hi]
    ok = tr["pm25"].notna() & tr["pm10"].notna() & (tr["pm25"] > 0)
    ratio = float((tr.loc[ok, "pm10"] / tr.loc[ok, "pm25"]).median()) if ok.any() else 1.0
    sigma = {
        st: {m: robust_sigma(g[m].to_numpy(float)) for m in MEASUREMENTS if m in g}
        for st, g in tr.groupby("station")
    }
    return {"ratio": ratio, "sigma": sigma}


class FleetState:
    """Run-time controls of the shared simulation clock (changed by `airq/cmd/fleet`)."""

    def __init__(self, speedup: float):
        self.speedup = speedup
        self.running = threading.Event()
        self.running.set()
        self.jump_to: pd.Timestamp | None = None
        self.sim_ts: pd.Timestamp | None = None

    def per_hour_s(self) -> float:
        return 3600.0 / self.speedup if self.speedup > 0 else 0.0


class FleetController:
    """Applies fleet and network commands. Pure (no MQTT): `handle` returns the ack to publish."""

    def __init__(self, state: FleetState, sensors: list[VirtualSensor], netem: NetEm):
        self.state, self.sensors, self.netem = state, sensors, netem

    def handle(self, payload: bytes | str) -> tuple[str, Ack] | None:
        try:
            cmd = parse_command(payload)
        except ValueError:
            return None  # devices answer malformed device commands; nothing to do here
        ts = self.state.sim_ts
        applied = None if ts is None else ts.to_pydatetime()
        if isinstance(cmd, FleetControl):
            err = self._fleet(cmd)
            return "fleet", Ack(
                cmd_id=cmd.cmd_id, source="fleet", ok=err is None, error=err, applied_at_ts=applied
            )
        if isinstance(cmd, NetControl):
            err = self._net(cmd)
            return "net", Ack(
                cmd_id=cmd.cmd_id, source="net", ok=err is None, error=err, applied_at_ts=applied
            )
        return None

    def _fleet(self, c: FleetControl) -> str | None:
        st = self.state
        if c.action == "pause":
            st.running.clear()
        elif c.action == "resume":
            st.running.set()
        elif c.action == "speedup":
            st.speedup = float(c.value)
        elif c.action == "jump":
            st.jump_to = pd.Timestamp(str(c.value))
        elif c.action == "reset":  # every intervention and every network emulation
            for s in self.sensors:
                s.reset()
            self.netem.reset()
        return None

    def _net(self, c: NetControl) -> str | None:
        known = {s.station for s in self.sensors}
        if c.target != ALL_TARGET and c.target not in known:
            return f"unknown station {c.target!r}"
        if c.reset:
            if c.target == ALL_TARGET:
                self.netem.reset()
            else:
                self.netem.per_station.pop(c.target, None)
            return None
        params = NetParams(c.loss_rate, c.delay_ms, c.jitter_ms, c.reorder_rate)
        self.netem.set(params, None if c.target == ALL_TARGET else c.target)
        return None


def run_fleet(
    raw: pd.DataFrame,
    stations: list[str],
    start: str,
    end: str,
    host: str,
    port: int,
    speedup: float = 3600,
    heartbeat_sim_min: int = 30,
    stop: threading.Event | None = None,
    on_hour=None,
    netem: NetEm | None = None,
    offline: list[str] | None = None,
    control: bool = False,
    calibration: dict | None = None,
    state: FleetState | None = None,
) -> dict:
    """Publish all stations for each simulated hour, in order, on one shared clock.

    `netem` emulates loss/delay/jitter/reordering on the sensor -> gateway link; `offline`
    stations are down for the whole run (they announce `offline` and publish nothing).
    `control=True` also listens on `airq/cmd/fleet` and `airq/cmd/net` (Senaryo Kontrol): pause,
    resume, speedup, jump, reset and live network emulation. `calibration` (train_calibration)
    sizes spike faults and the coupled PM10 response of the device commands.
    """
    stop = stop or threading.Event()
    if control and netem is None:
        netem = NetEm()  # live network commands need an emulator, even if it starts neutral
    state = state or FleetState(speedup)
    cal = calibration or {}
    runner = DelayedRunner() if netem is not None else None
    down = set(offline or [])
    all_sensors = [
        VirtualSensor(
            s,
            raw[raw["station"] == s][raw.columns],
            host,
            port,
            netem,
            runner,
            cal.get("ratio", 1.0),
            cal.get("sigma", {}).get(s),
        )
        for s in stations
    ]
    sensors = [s for s in all_sensors if s.station not in down]
    hours = pd.date_range(start, end, freq="h")
    beats = max(1, 60 // heartbeat_sim_min)
    published = 0
    ctl_client = None
    try:
        for s in all_sensors:
            s.connect()
        for s in all_sensors:
            if s.station in down:
                s.close()  # announces `offline` (retained) and never publishes data
        if control:
            ctl_client = _start_controller(FleetController(state, sensors, netem), host, port)
        idx, due = 0, time.monotonic()
        while idx < len(hours) and not stop.is_set():
            if not state.running.is_set():  # paused: the simulated clock stands still
                state.running.wait(0.2)
                due = time.monotonic()
                continue
            if state.jump_to is not None:
                idx, state.jump_to = int(hours.searchsorted(state.jump_to)), None
                due = time.monotonic()
                continue
            ts = hours[idx]
            state.sim_ts = ts
            per_hour_s = state.per_hour_s()
            for s in sensors:  # same ts for all stations, in order
                if s.tick(ts) is not None:
                    published += 1
            for b in range(beats):
                beat_ts = ts + pd.Timedelta(minutes=b * heartbeat_sim_min)
                if b > 0 and per_hour_s:
                    _sleep_until(due + b * per_hour_s / beats, stop)
                for s in sensors:
                    if not s.offline_by_command:
                        s.publish_heartbeat(beat_ts)
            if on_hour:
                on_hour(ts)
            idx += 1
            due += per_hour_s
            if per_hour_s:
                _sleep_until(due, stop)
    finally:  # Ctrl+C or end: flush delayed messages, publish `offline`, then disconnect
        if ctl_client is not None:
            disconnect(ctl_client)
        if runner is not None:
            runner.drain(60.0)
            runner.stop()
        for s in sensors:
            s.close()
    return {
        "hours": len(hours),
        "messages": published,  # readings generated by the devices that were up
        "dropped": sum(s.dropped for s in sensors),  # never published (emulated link loss)
        "devices": len(sensors),
        "offline_devices": len(down),
    }


def _start_controller(ctl: FleetController, host: str, port: int):
    client = make_client("fleet-controller")

    def on_message(c, _u, msg):
        out = ctl.handle(msg.payload)
        if out is not None:
            source, ack = out
            c.publish(topics.topic(topics.CMD_ACK, source), ack.to_json(), qos=topics.CMD_ACK.qos)

    client.on_message = on_message
    connect_blocking(client, host, port)
    client.subscribe(
        [
            (topics.topic(topics.CMD_FLEET), topics.CMD_FLEET.qos),
            (topics.topic(topics.CMD_NET), topics.CMD_NET.qos),
        ]
    )
    return client


def _sleep_until(target: float, stop: threading.Event) -> None:
    delay = target - time.monotonic()
    if delay > 0:
        stop.wait(delay)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--speedup", type=float, default=3600)
    ap.add_argument("--stations", default="all", help="'all' or comma-separated names")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--broker", default="127.0.0.1:1883")
    ap.add_argument("--netem", default="", help="e.g. loss=0.1,delay=200,jitter=20,reorder=0.05")
    ap.add_argument("--offline", default="", help="comma-separated stations that are down")
    ap.add_argument("--control", action="store_true", help="listen to airq/cmd/* (Senaryo Kontrol)")
    args = ap.parse_args()

    cfg = load_config()
    paths = resolve_paths(cfg["paths"])
    hits = sorted((paths["raw"] / "beijing").rglob("PRSA_Data_*.csv"))
    if not hits:
        raise SystemExit("Raw data not found; run `python -m scripts.download_data` first.")
    raw = raw_all = load_raw(hits[0].parent)
    stations = (
        cfg["data"]["stations"]
        if args.stations == "all"
        else [s.strip() for s in args.stations.split(",")]
    )
    raw = raw[raw["station"].isin(stations)]
    host, port = args.broker.rsplit(":", 1)
    netem = NetEm(NetParams.parse(args.netem), seed=args.seed) if args.netem else None
    calibration = train_calibration(raw_all, cfg) if args.control else None
    stop = threading.Event()
    try:
        print(
            run_fleet(
                raw,
                stations,
                args.start,
                args.end,
                host,
                int(port),
                args.speedup,
                stop=stop,
                netem=netem,
                offline=[x for x in args.offline.split(",") if x],
                control=args.control,
                calibration=calibration,
            )
        )
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
