# airq-iot

IoT-based air quality monitoring with multi-horizon PM2.5 forecasting and early warning.
Real measurements from the Beijing Multi-Site Air-Quality dataset are replayed through virtual
IoT devices over MQTT (trace-driven emulation), validated at an edge gateway, and forecast
(1/6/24 h) with LightGBM.

> **Status:** work in progress (scaffold). Results, demo GIF and Colab badges will be added as
> the project progresses. Türkçe: [README.tr.md](README.tr.md).

## Architecture (planned)

`VirtualSensor x12 -> MQTT -> Edge gateway -> Ingest -> SQLite -> Predictor -> FastAPI -> Streamlit`

The project specification is kept locally and is not part of this repository.

## Quick start (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pre-commit install
pytest -m "not broker and not slow"
```

MQTT broker: install Mosquitto (`winget install EclipseFoundation.Mosquitto`) and run
`mosquitto -c configs\mosquitto.conf -v`; without it, `python -m airq.iot.broker` starts a pure-Python
fallback (amqtt).

## Colab notebooks

The ML part (data, EDA, forecasting, early warning, robustness) reproduces in the browser; the IoT
live system (broker, device fleet, edge, dashboard, demo) runs locally only.

| Notebook | What it does |
|---|---|
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/00_setup_colab.ipynb) `00_setup_colab` | install, download + SHA-256 check, build the cleaned dataset |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/01_data_eda.ipynb) `01_data_eda` | Table 1, correlation / missing-data figure, episodes |

Each notebook starts with `QUICK = True` (2 stations, a few minutes). Set `QUICK = False` for the full run.
Results can be exported as `airq_artifacts_<date>.zip` and imported locally with
`python -m scripts.import_artifacts <zip>` (checks the model manifest).

## Limitations

Beijing data comes from reference stations, not low-cost sensors; the evaluation is a
trace-driven emulation, not a field study.

## License

MIT. Dataset: Beijing Multi-Site Air-Quality Data, UCI ML Repository,
doi:10.24432/C5RK5G, licensed CC BY 4.0 (verified on the UCI dataset page).

## Authors

Orhan Akbaba, Furkan Topçu — Istanbul Medeniyet University, Computer Engineering (IoT course project).
