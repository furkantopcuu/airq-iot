"""One-command demo (python -m scripts.demo). See airq.pipelines.demo and README.

--offline   open the dashboard on a recorded SQLite file (no broker, no devices)
--smoke     start the stack on a private broker, send one command through the API, stop
--speedup N play the replay N times faster than real time (default 3600 = 1 s per simulated hour)
--realistic slow, realistic pace: 60x = one new reading per station per minute (a free-test mode)
"""

from __future__ import annotations

import argparse
import json
import sys

from airq.config import load_config
from airq.pipelines.demo import run_demo, smoke

REALISTIC_SPEEDUP = 60.0  # one simulated hour per minute: values change slowly, like a real station


def demo_speedup(cfg: dict, speedup: float | None, realistic: bool) -> dict:
    """The config with the demo speed overridden (the fast default is unchanged)."""
    if speedup is not None and realistic:
        raise SystemExit("--speedup ile --realistic birlikte kullanılmaz")
    value = REALISTIC_SPEEDUP if realistic else speedup
    if value is None:
        return cfg
    if value <= 0 or value >= cfg["demo"]["warmup_speedup"]:
        raise SystemExit(f"hız 0 ile {cfg['demo']['warmup_speedup']:g} arasında olmalı")
    sec_per_hour = 3600.0 / value
    print(
        f"Hız: {value:g}x -> her istasyon {sec_per_hour:g} sn'de bir yeni ölçüm alır "
        f"(varsayılan {cfg['demo']['speedup']:g}x = 1 sn/saat). Planlı senaryolar bu hızda "
        "uzun sürer; serbest test için uygundur. Panoda Filo > Hız ile canlı değiştirilebilir."
    )
    return {**cfg, "demo": {**cfg["demo"], "speedup": float(value)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="recorded SQLite, no broker")
    ap.add_argument("--smoke", action="store_true", help="10 s end-to-end self test")
    ap.add_argument("--db", help="database file (default data/demo.db; --offline: latest run)")
    ap.add_argument("--keep-db", action="store_true", help="do not wipe the demo database first")
    ap.add_argument("--port", type=int, help="MQTT broker port (default from the config)")
    ap.add_argument("--api-port", type=int)
    ap.add_argument("--dashboard-port", type=int)
    ap.add_argument(
        "--duration", type=float, help="stop by itself after N seconds (rehearsal, tests)"
    )
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-predictor", action="store_true", help="skip the forecaster (plumbing)")
    ap.add_argument("--speedup", type=float, help="replay speed (x); default from the config")
    ap.add_argument(
        "--realistic",
        action="store_true",
        help=f"slow pace: {REALISTIC_SPEEDUP:g}x (1 reading/min)",
    )
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a console without Turkish letters must not crash
    cfg = load_config()
    if args.smoke:
        result = smoke(cfg)
        print(json.dumps(result))
        print("SMOKE OK" if result["ok"] else "SMOKE FAILED")
        return 0 if result["ok"] else 1
    return run_demo(demo_speedup(cfg, args.speedup, args.realistic), args)


if __name__ == "__main__":
    sys.exit(main())
