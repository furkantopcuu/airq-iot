"""Record the demo run shipped as a release asset (python -m scripts.record_demo_db).

Plays a haze episode with a ramp and spike faults on the real stack (about 4 minutes, needs the
trained models and the data) and writes data/demo_recorded.db (< 5 MB). Then
`python -m scripts.make_release_assets` packs it. Replay it with `python -m scripts.demo --offline`.
"""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.pipelines.scenarios import record_demo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--speedup", type=float, default=7200.0)
    args = ap.parse_args()
    out = record_demo(load_config(), args.speedup)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
