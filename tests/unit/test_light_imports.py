"""The ML, figure and table stages must run on a plain ML install (no MQTT / server packages).

CI's `notebooks` job installs only the `ml` and `dev` extras; a figure stage that imported the
scenario runner (which needs paho-mqtt) broke it once.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLOCKED = (
    "paho",
    "paho.mqtt",
    "paho.mqtt.client",
    "amqtt",
    "fastapi",
    "uvicorn",
    "psutil",
    "streamlit",
)


def test_figure_and_table_stages_do_not_import_the_iot_stack():
    code = f"""
import sys
for m in {BLOCKED!r}:
    sys.modules[m] = None
import pandas as pd
import airq.eval.paired, airq.pipelines.figures, airq.pipelines.tables
d = pd.DataFrame({{"fault": ["f", "f"], "start": ["s", "s"], "edge": ["off", "on"],
                   "mae_window_h1": [3.0, 1.0], "mae_window_h6": [2.0, 2.0],
                   "peak_forecast_h6": [9.0, 4.0]}})
out = airq.eval.paired.paired_differences(d)
assert out["mae_window_h1_diff"].iloc[0] == 2.0
assert "airq.iot.broker" not in sys.modules
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-800:]


def test_figure_and_table_modules_never_reference_the_scenario_runner():
    for rel in ("src/airq/pipelines/figures.py", "src/airq/pipelines/tables.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "pipelines.scenarios" not in text, rel
