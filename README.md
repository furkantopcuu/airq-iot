# airq-iot

[![CI](https://github.com/furkantopcuu/airq-iot/actions/workflows/ci.yml/badge.svg)](https://github.com/furkantopcuu/airq-iot/actions/workflows/ci.yml)

IoT-based air quality monitoring with multi-horizon PM2.5 forecasting and early warning.
Real measurements from the Beijing Multi-Site Air-Quality dataset are replayed through 12 virtual
IoT devices over MQTT (trace-driven emulation), validated at an edge gateway, stored in SQLite,
forecast 1 / 6 / 24 h ahead with LightGBM, and shown on a live dashboard. A command channel
(MQTT `cmd` / `ack`) lets you change sensor values, inject sensor faults, degrade the network and
switch the edge filter **while the system runs**, and a scoreboard measures how the forecasts and
warnings react. Türkçe: [README.tr.md](README.tr.md).

![Architecture](reports/figures/architecture.png)

## What is in the box

| Layer | What | Where |
|---|---|---|
| Devices | 12 virtual sensors (one MQTT client each, LWT, heartbeat, `seq`), network emulation (loss, delay, jitter, reordering) | `src/airq/devices/` |
| Edge | validation, data-quality flags (range, rate jump, stuck, PM2.5 <= PM10, missing, `seq` gaps), optional filter | `src/airq/edge/` |
| Server | ingest (single SQLite writer), predictor (same `build_features` as offline), FastAPI read + control endpoints | `src/airq/server/` |
| Control | `cmd` / `ack` channel, device modes (manual, offset, scale, ramp, spike / stuck / dropout, offline), fleet and edge control, 7 ready-made scenarios | `src/airq/scenarios/`, `configs/scenarios/` |
| ML | leakage-safe features, persistence / seasonal-naive / ridge / LightGBM, Optuna, LOSO, SHAP, DM tests | `src/airq/features/`, `src/airq/models/`, `src/airq/pipelines/` |
| UI | Streamlit dashboard (6 pages, scenario control panel) | `src/airq/dashboard/` |

## Results

Everything below is generated from `reports/tables/*.csv` by `python -m scripts.make_tables --readme`.
Every finding, including the negative ones and the caveats, is logged in
[docs/KARARLAR.md](docs/KARARLAR.md); the reasoning behind each technology choice is in
[docs/NEDEN.md](docs/NEDEN.md).

**RQ1 - forecast error on the held-out test year (RMSE, µg/m³; improvement over persistence in %)**

<!-- TABLE:rq1_main -->
| Model | RMSE h=1 | RMSE h=6 | RMSE h=24 | Δ% vs B0 h=1 | Δ% vs B0 h=6 | Δ% vs B0 h=24 |
|---|---|---|---|---|---|---|
| B0 persistence | 19.65 | 54.88 | 88.12 | 0.0 | 0.0 | 0.0 |
| B1 seasonal naive | 88.14 | 88.16 | 88.12 | -348.6 | -60.6 | 0.0 |
| B2 ridge (k=0) | 18.54 | 50.05 | 73.66 | 5.6 | 8.8 | 16.4 |
| M1 LightGBM (k=0) | 17.85 | 48.88 | 73.53 | 9.1 | 10.9 | 16.6 |
| M2a LightGBM (k=3) | 16.99 | 47.89 | 73.35 | 13.5 | 12.7 | 16.8 |
| M2b LightGBM (k=11) | 17.08 | 46.60 | 73.29 | 13.1 | 15.1 | 16.8 |
<!-- /TABLE:rq1_main -->

![RMSE by horizon](reports/figures/rq1_horizon.png)

**RQ3b - faulty sensor inputs: RMSE increase with the edge filter off vs on (rows whose last 24 h contain a fault)**

<!-- TABLE:rq3b -->
| Method | h | RMSE clean | Damage, edge off | Damage, edge on | Recovered (%) |
|---|---|---|---|---|---|
| B0 persistence | 1 h | 20.42 | 45.74 | 7.27 | 84.1 |
| B0 persistence | 6 h | 56.97 | 24.70 | 1.75 | 92.9 |
| B0 persistence | 24 h | 90.19 | 13.94 | 0.52 | 96.2 |
| M1 LightGBM (k=0) | 1 h | 19.04 | 27.00 | 18.96 | 29.8 |
| M1 LightGBM (k=0) | 6 h | 51.03 | 8.83 | 8.12 | 8.1 |
| M1 LightGBM (k=0) | 24 h | 76.01 | 1.77 | 1.58 | 10.8 |
| M2b LightGBM (k=11) | 1 h | 18.09 | 22.36 | 14.65 | 34.5 |
| M2b LightGBM (k=11) | 6 h | 48.40 | 2.34 | 1.54 | 34.1 |
| M2b LightGBM (k=11) | 24 h | 75.96 | 0.57 | 0.56 | 2.2 |
<!-- /TABLE:rq3b -->

**Senaryo Kontrol - hypotheses written down before running, and what the live system did** (one run per scenario)

<!-- TABLE:scenarios -->
| Scenario | Item | Metric | Expected | Reference | Measured | Verdict |
|---|---|---|---|---|---|---|
| ag_bozulmasi | net-degraded | delivery_ratio | less than | 0.95 | 0.88 | confirmed |
| ag_bozulmasi | net-degraded | latency_p95_ms | greater than | 250.00 | 318.00 | confirmed |
| bolgesel_artis | regional-ramp | warned | true |  | True | confirmed |
| cihaz_kopmasi | three-offline | min_n_neighbors | less than | 11.00 | 8.00 | confirmed |
| gercek_haze_replay | haze-replay | warned | true |  | True | confirmed |
| gercek_haze_replay | haze-replay | lead_time_h | greater than | 0.00 | 22.00 | confirmed |
| sensor_sicramasi | spike-edge-off | peak_forecast_h6 | greater than | 54.00 | 87.69 | confirmed |
| sensor_sicramasi | spike-edge-off | warned | true |  | True | confirmed |
| sensor_takilmasi | stuck-edge-off | mae_next_6h_h6 | greater than | 12.57 | 10.54 | refuted |
| yerel_artis | local-ramp | warned | true |  | True | confirmed |
| yerel_artis | neighbor-huairou | peak_forecast_h6 | less than | 101.91 | 39.03 | confirmed |
<!-- /TABLE:scenarios -->

![Spike and stuck faults, edge off vs on](reports/figures/scenarios_edge.png)

The live-system benchmark (RQ3a: loss, delay, offline devices, CPU and memory) is in
`reports/tables/rq3a_bench.csv` and `reports/figures/rq3a_system.png`.

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

MQTT broker: install Mosquitto (`winget install EclipseFoundation.Mosquitto`); without it
`python -m airq.iot.broker` starts a pure-Python fallback (amqtt) and the demo does this for you.

## Run the live demo (one command)

The demo needs the cleaned data and the trained models. Models are not stored in the repository
(release asset); build them once with `python -m scripts.run_all` (see below) or restore the
`airq_artifacts_<date>.zip` of a Colab run with `python -m scripts.import_artifacts <zip>`.

```powershell
python -m scripts.demo
```

It checks for a broker (starting one if needed), starts edge, ingest, predictor, the device fleet,
the API and the dashboard as separate processes, fast-forwards the 240 h predictor warm-up, then
plays one simulated hour per second inside a real haze episode and opens the dashboard.
`Ctrl+C` stops everything.

1. **Planned flow** - on the *Senaryo Kontrol + Canlı izleme* page open "Hazır senaryolar" and play
   `gercek_haze_replay`, `sensor_takilmasi`, `cihaz_kopmasi`, `ag_bozulmasi` in turn.
2. **Free test** - pick a station and a value in "Müdahale (cihaz)" (for example *Dongsi PM2.5 ramps
   to 300 over 6 h*). Out-of-range values are refused unless you tick the faulty-input box; "Her şeyi
   sıfırla" always returns to the clean state.
3. An instant jump is flagged and nulled by the edge filter (`rate_jump`) - that is the edge doing its
   job; use `ramp` for a realistic pollution rise, or switch the filter off to see the damage.

`python -m scripts.demo --offline` opens the dashboard on a recorded SQLite file without a broker
(controls are disabled); `python -m scripts.demo --smoke` is a 10-second end-to-end self test.

## Reproduce the results

```powershell
python -m scripts.run_all --home ..\airq-repro --quick   # minutes: 2 stations, no Optuna (pipeline smoke test)
python -m scripts.run_all --home ..\airq-repro           # full: hours (Optuna 20 trials per study)
python -m scripts.run_all --home ..\airq-repro --with-system   # + RQ3a benchmark and scenarios (needs a broker)
python -m scripts.run_all --check                        # verify that every output exists
```

`--home` keeps a reproduction away from the committed results (a QUICK run is refused without it).
Stages are cached by their outputs, so an interrupted run continues. The test split is evaluated
once per home (guard files); a fresh home never needs `--force`.

### Colab notebooks

The ML part reproduces in the browser; the live IoT system (broker, fleet, edge, dashboard, demo,
RQ3a, scenarios) runs locally only because Colab has no persistent services or reliable latency.

| Notebook | What it does |
|---|---|
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/00_setup_colab.ipynb) `00_setup_colab` | install, download + SHA-256 check, build the cleaned dataset |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/01_data_eda.ipynb) `01_data_eda` | dataset table, correlation / missing-data figure, episodes |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/02_forecast_rq1.ipynb) `02_forecast_rq1` | RQ1: baselines, LightGBM, ablation, LOSO, SHAP |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/03_early_warning_rq2.ipynb) `03_early_warning_rq2` | RQ2: warning rule, haze episodes, lead time |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/04_robustness_rq3b.ipynb) `04_robustness_rq3b` | RQ3b: faulty inputs, edge filter on / off |
| [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/furkantopcuu/airq-iot/blob/main/notebooks/06_figures_tables.ipynb) `06_figures_tables` | all paper figures and tables |

Each notebook starts with `QUICK = True` (2 stations, a few minutes); set `QUICK = False` for the
full run. Results export as `airq_artifacts_<date>.zip` and import locally with
`python -m scripts.import_artifacts <zip>` (checks the model manifest).

## Tests

```powershell
pytest -m "not broker and not slow"      # fast: unit tests, notebooks excluded
pytest                                   # everything, with a real broker (Mosquitto and amqtt)
```

CI runs the unit tests on Windows (required) and Ubuntu, and the notebooks in fixture mode.
The broker integration job on Ubuntu is currently failing and not required (open item in
`docs/KARARLAR.md`); the full test suite has only been verified on Windows.

## Limitations

- Beijing data comes from reference stations, not low-cost sensors; the evaluation is a
  trace-driven emulation, not a field study.
- Network impairment is emulated in the application layer (a lost message is never published), not
  with OS-level `tc netem` (Windows). MQTT retransmission therefore plays no role, and the effect of
  TCP queueing on tail latency is **not** measured.
- All system measurements come from one machine (absolute numbers are machine-specific); the RQ3a
  plan was shortened to fit the time budget, and each scenario was run once (no variance).
- The command channel has no authentication (localhost only); a real deployment needs MQTT ACLs
  and TLS.
- Models underestimate extreme pollution peaks (see `reports/tables/rq1_extreme.csv`).

## Layout

`src/airq/` library - `scripts/` command line entry points - `configs/` YAML config and scenarios -
`notebooks/` thin Colab notebooks (generated by `scripts/build_notebooks.py`) - `reports/` result
tables, metrics, figures, scenario runs - `paper/tables/` generated LaTeX / Markdown tables -
`docs/` decision log and per-component rationale - `tests/`.

## License

MIT. Dataset: Beijing Multi-Site Air-Quality Data, UCI ML Repository,
doi:10.24432/C5RK5G, licensed CC BY 4.0 (verified on the UCI dataset page).

## Authors

Orhan Akbaba, Furkan Topçu - Istanbul Medeniyet University, Computer Engineering (IoT course project).
See [CITATION.cff](CITATION.cff) to cite.
