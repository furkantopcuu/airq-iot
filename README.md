# airq-iot

IoT-based air quality monitoring with multi-horizon PM2.5 forecasting and early warning.
Real measurements from the Beijing Multi-Site Air-Quality dataset are replayed through virtual
IoT devices over MQTT (trace-driven emulation), validated at an edge gateway, and forecast
(1/6/24 h) with LightGBM.

> **Status:** work in progress (scaffold). Results, demo GIF and Colab badges will be added as
> the project progresses. Türkçe: [README.tr.md](README.tr.md).

## Architecture (planned)

`VirtualSensor x12 -> MQTT -> Edge gateway -> Ingest -> SQLite -> Predictor -> FastAPI -> Streamlit`

See [docs/TALIMAT.md](docs/TALIMAT.md) for the full specification.

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

## Limitations

Beijing data comes from reference stations, not low-cost sensors; the evaluation is a
trace-driven emulation, not a field study.

## License

MIT. Dataset: Beijing Multi-Site Air-Quality Data, UCI ML Repository, doi:10.24432/C5RK5G
(verify license on the UCI page).
