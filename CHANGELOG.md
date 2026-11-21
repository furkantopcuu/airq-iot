# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/). Every finding behind a change, including
negative results, is logged in [docs/KARARLAR.md](docs/KARARLAR.md) (Turkish).

## [Unreleased]

### Added
- **Paper** (`paper/`): IEEEtran draft, Turkish text with an English abstract, 8 pages, compiled on Overleaf. Every number in the text is a macro generated from `reports/` (`paper/NUMBERS.md` maps each to its source), checked by `scripts/check_paper.py` and by tests that re-derive the numbers independently.
- `ARCHITECTURE.md`, `FINDINGS.md`, `scripts/quickstart.sh` (Linux, macOS, WSL, Git Bash).
- **Presentation material** (`slides/`): outline, speaker notes, likely jury questions (generated from `slides/src/` with the paper's numbers), dashboard screenshots and a silent backup video.
- `slides/airq_iot_sunum.pptx` (23 slides with speaker notes, built by `scripts/make_pptx.py` from the paper's numbers) and `slides/hazirlik.md`, a study guide for the talk.
- `reports/tables/rq1_tuning_convergence.csv`: evidence for the 20-trial Optuna budget.
- `scripts.demo --realistic` (60x, one reading per station per minute) and `--speedup N`: a slow, realistic pace next to the fast default.

### Fixed
- `demo` and `demo --smoke` now say which input (raw data, trained models) is missing and which command provides it, instead of failing with "stations never appeared".
- The RQ3a table caption no longer calls the full grid a "reduced plan".

## [0.3.0] - 2026-11-20

### Added
- **RQ4 forecast uncertainty:** LightGBM quantile models (alpha 0.1 / 0.5 / 0.9) per horizon, a
  validation-only interval calibration, a q90-based early-warning evaluation, the q10-q90 band on the
  dashboard (`predictor --quantiles`), notebook `05`, a figure and tables. The protocol and the
  hypothesis were committed before the test split was evaluated.
- **RQ3a full benchmark grid** (the specified grid, 57 runs, 3 repetitions) with a per-configuration
  count of runs in which the predictor fell behind and the median warning latency.
- **Paired A/B scenarios:** the same sensor-fault window run with the edge filter off and on, over
  three start dates (12 runs, `run_scenarios --ab`).
- `compare_reports` (does a reproduction match the committed numbers?), `run_all --check`,
  `demo --smoke` and `demo --offline`.
- CI: the broker integration job uploads a JUnit report when it fails.
- `SECURITY.md`, issue templates, `CODEOWNERS`, Dependabot, dependency `constraints.txt`.

### Security
- Dashboard HTML-escapes station names, flags and labels coming from MQTT; Streamlit binds to
  `127.0.0.1` with XSRF protection; the API refuses non-loopback `Host` and `Origin` headers on
  state-changing requests; `.gitignore` blocks `.env*`, keys and credential files.
- `tests/unit/test_security.py`, `bandit` and `pip-audit` in CI; full-history secret scan (clean).

### Changed
- The predictor no longer waits for devices that announced `offline` (retained status); before, one
  offline device added the 500 ms wait to every hour (found by the RQ3a benchmark).
- `forecast.optuna_trials` is 20 in the config, matching every committed result (it said 40).
- The Optuna study of M2a h=1 was re-run without interruption: reproducible now (test RMSE
  16.9937 -> 16.9919, the only changed row of the main table).
- Google Colab is out of scope; its badges and claims were removed from the README.
- `run_one` starts every benchmark run from an empty database (a re-run used to append to the old one).

### Fixed
- Test helpers ignore retained messages that amqtt hands to wildcard subscribers.
- Scorecard "lead time": an onset must follow at least 6 h below the threshold and a warning only
  counts for the episode it targets (scoring version 2; version 1 results are kept for audit).

## [0.2.0] - 2026-11-20

### Added
- Results for RQ1 (forecast), RQ2 (early warning) and RQ3a / RQ3b (system and faulty-input
  robustness), the live system (virtual devices, edge gateway, ingest, predictor, API) and the
  Streamlit dashboard.
- **Senaryo Kontrol:** MQTT `cmd` / `ack` command channel, device modes, fleet / network / edge
  control, seven ready-made scenarios with written hypotheses, a scoreboard and `run_scenarios`.
- LaTeX / Markdown result tables (`make_tables`), figures, `demo.py`, `run_all.py`, notebook `06`.

## [0.1.0] - not tagged
Foundation: data pipeline with chronological split and leakage tests, features, baselines and LightGBM,
MQTT core, edge quality rules and CI.
