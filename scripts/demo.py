"""One-command demo (python -m scripts.demo). See airq.pipelines.demo and README.

--offline   open the dashboard on a recorded SQLite file (no broker, no devices)
--smoke     start the stack on a private broker, send one command through the API, stop
"""

from __future__ import annotations

import argparse
import json
import sys

from airq.config import load_config
from airq.pipelines.demo import run_demo, smoke


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
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a console without Turkish letters must not crash
    cfg = load_config()
    if args.smoke:
        result = smoke(cfg)
        print(json.dumps(result))
        print("SMOKE OK" if result["ok"] else "SMOKE FAILED")
        return 0 if result["ok"] else 1
    return run_demo(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
