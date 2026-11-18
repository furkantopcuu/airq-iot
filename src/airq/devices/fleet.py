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
from airq.devices.virtual_sensor import VirtualSensor
from airq.env import resolve_paths


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
) -> dict:
    """Publish all stations for each simulated hour, in order, on one shared clock."""
    stop = stop or threading.Event()
    sensors = [
        VirtualSensor(s, raw[raw["station"] == s][raw.columns], host, port) for s in stations
    ]
    hours = pd.date_range(start, end, freq="h")
    per_hour_s = 3600.0 / speedup if speedup > 0 else 0.0
    beats = max(1, 60 // heartbeat_sim_min)
    published = 0
    try:
        for s in sensors:
            s.connect()
        t0 = time.monotonic()
        for i, ts in enumerate(hours):
            if stop.is_set():
                break
            for s in sensors:  # same ts for all stations, in order
                s.publish_reading(ts)
                published += 1
            for b in range(beats):
                beat_ts = ts + pd.Timedelta(minutes=b * heartbeat_sim_min)
                if b > 0 and per_hour_s:
                    _sleep_until(t0 + i * per_hour_s + b * per_hour_s / beats, stop)
                for s in sensors:
                    s.publish_heartbeat(beat_ts)
            if on_hour:
                on_hour(ts)
            if per_hour_s:
                _sleep_until(t0 + (i + 1) * per_hour_s, stop)
    finally:  # Ctrl+C or end: publish `offline` first, then disconnect
        for s in sensors:
            s.close()
    return {"hours": len(hours), "messages": published, "devices": len(sensors)}


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
    args = ap.parse_args()

    cfg = load_config()
    paths = resolve_paths(cfg["paths"])
    hits = sorted((paths["raw"] / "beijing").rglob("PRSA_Data_*.csv"))
    if not hits:
        raise SystemExit("Raw data not found; run `python -m scripts.download_data` first.")
    raw = load_raw(hits[0].parent)
    stations = (
        cfg["data"]["stations"]
        if args.stations == "all"
        else [s.strip() for s in args.stations.split(",")]
    )
    raw = raw[raw["station"].isin(stations)]
    host, port = args.broker.rsplit(":", 1)
    stop = threading.Event()
    try:
        print(
            run_fleet(raw, stations, args.start, args.end, host, int(port), args.speedup, stop=stop)
        )
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
