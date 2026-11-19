"""Live predictor: edge telemetry -> rolling buffer -> build_features -> LightGBM -> SQLite.

It uses the SAME `clean()` and `build_features()` as offline training (parity, spec 8.5).
Per simulated hour it waits at most `predictor_wait_ms` for the other stations' readings; stations
that have not arrived are treated as missing, so `n_neighbors_available` shows the network damage.

Run: python -m airq.server.predictor [--broker 127.0.0.1:1883] [--k 11]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from airq.config import config_hash
from airq.data.clean import clean
from airq.features.build import FeatureConfig, build_features
from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import MEASUREMENTS, Telemetry, WarningMsg
from airq.models.manifest import git_short_hash, load_model_checked
from airq.server import db

HISTORY_H = 168 + 72  # longest lookback (168 h lag) + rolling window headroom


@dataclass
class PredictionLog:
    """What the predictor computed for one (station, ts): used by the parity test and the API."""

    station: str
    ts: pd.Timestamp
    features: pd.Series
    yhat: dict[int, float]


@dataclass
class OnlinePredictor:
    cfg: dict
    models_dir: Path
    k: int
    stations: list[str]
    neighbors: dict[str, list[str]] | None = None
    wait_s: float = 0.5
    history_h: int = HISTORY_H
    keep_log: bool = False
    thresholds: dict | None = None  # {"150": {"6": delta, ...}} from warning_thresholds.json
    cooldown_h: int = 6
    log: list[PredictionLog] = field(default_factory=list)
    late_dropped: int = 0
    expired: int = 0  # timestamps predicted after the wait ran out (some station missing)

    def __post_init__(self):
        self.buf: dict[str, dict[pd.Timestamp, dict]] = {s: {} for s in self.stations}
        self.first_seen: dict[pd.Timestamp, float] = {}
        self.last_done: pd.Timestamp | None = None
        self.earliest: pd.Timestamp | None = None
        self.models: dict[int, object] = {}
        self.fcfg = FeatureConfig.from_cfg(self.cfg, k=self.k, neighbors=self.neighbors)
        self.version = f"{config_hash(self.cfg)}-{git_short_hash()}"
        self._lock = threading.Lock()
        self._last_alert: dict[tuple, pd.Timestamp] = {}

    # --- input ---------------------------------------------------------------------------
    def add(self, msg: Telemetry, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        ts = pd.Timestamp(msg.ts)
        with self._lock:
            if msg.station not in self.buf:
                return  # unknown station (not part of this predictor's network)
            if self.last_done is not None and ts <= self.last_done:
                self.late_dropped += 1  # already predicted: stored by ingest, never re-predicted
                return
            row = {m: getattr(msg, m) for m in MEASUREMENTS}
            row.update(station=msg.station, ts=ts, wd=msg.wd)
            self.buf[msg.station][ts] = row
            self.first_seen.setdefault(ts, now)
            self.earliest = ts if self.earliest is None else min(self.earliest, ts)

    # --- scheduling ----------------------------------------------------------------------
    def ready(self, now: float | None = None) -> list[pd.Timestamp]:
        """Timestamps to predict now, strictly in order: complete, or past their wait deadline."""
        now = time.monotonic() if now is None else now
        out = []
        with self._lock:
            for ts in sorted(
                t for t in self.first_seen if self.last_done is None or t > self.last_done
            ):
                complete = all(ts in self.buf[s] for s in self.stations)
                if complete or now - self.first_seen[ts] >= self.wait_s:
                    out.append(ts)
                else:
                    break  # keep order: a later hour never overtakes an earlier one
        return out

    # --- prediction ----------------------------------------------------------------------
    def _window(self, ts: pd.Timestamp) -> pd.DataFrame:
        lo = ts - pd.Timedelta(hours=self.history_h - 1)
        rows = [r for s in self.stations for t, r in self.buf[s].items() if lo <= t <= ts]
        return pd.DataFrame(rows)

    def predict(self, ts: pd.Timestamp) -> list[dict]:
        """Predict h=1/6/24 for every station that reported at `ts`; returns DB rows."""
        with self._lock:
            warm = self.earliest is not None and ts - self.earliest >= pd.Timedelta(
                hours=self.history_h - 1
            )
            present = [s for s in self.stations if ts in self.buf[s]]
            missing = len(present) < len(self.stations)
            win = self._window(ts) if warm else None
            self.last_done = ts
            self.first_seen.pop(ts, None)
            if missing:
                self.expired += 1
            self._prune(ts)
        if not warm or win is None or win.empty:
            return []
        lo = ts - pd.Timedelta(hours=self.history_h - 1)
        cleaned = clean(win, str(lo), str(ts), self.cfg["data"]["ffill_limit"])
        feats, meta = build_features(cleaned, self.fcfg)
        now_rows = feats[feats["ts"] == ts]
        rows = []
        for _, f in now_rows.iterrows():
            station = f["station"]
            yhat = {}
            for h in self.cfg["forecast"]["horizons"]:
                model = self._model(h, meta.feature_names)
                x = pd.DataFrame([f[meta.feature_names]]).astype(
                    {c: feats[c].dtype for c in meta.feature_names}
                )
                yhat[h] = float(model.predict(x)[0])
                rows.append(
                    {
                        "station": station,
                        "made_at_ts": ts.isoformat(),
                        "target_ts": (ts + pd.Timedelta(hours=h)).isoformat(),
                        "horizon": h,
                        "yhat": yhat[h],
                        "q10": None,
                        "q90": None,
                        "n_neighbors": (
                            int(f["n_neighbors_available"])
                            if "n_neighbors_available" in f
                            else None
                        ),
                        "model_version": self.version,
                    }
                )
            if self.keep_log:
                self.log.append(PredictionLog(station, ts, f[meta.feature_names], yhat))
        return rows

    def make_warnings(self, rows: list[dict]) -> list[dict]:
        """Apply the early-warning rule (yhat > theta - delta) with the 6 h cooldown (spec 5.1).

        Same logic as the offline `apply_cooldown`: an alert opens, the next ones are suppressed
        until `cooldown_h` hours have passed since it opened.
        """
        if not self.thresholds:
            return []
        out = []
        for r in rows:
            made = pd.Timestamp(r["made_at_ts"])
            for theta, by_h in self.thresholds.items():
                delta = by_h.get(str(r["horizon"]))
                if delta is None or not r["yhat"] > float(theta) - float(delta):
                    continue
                key = (r["station"], theta, r["horizon"])
                last = self._last_alert.get(key)
                if last is not None and made - last < pd.Timedelta(hours=self.cooldown_h):
                    continue
                self._last_alert[key] = made
                out.append(
                    {
                        "station": r["station"],
                        "made_at_ts": r["made_at_ts"],
                        "horizon": r["horizon"],
                        "threshold": float(theta),
                        "yhat": r["yhat"],
                        "delta": float(delta),
                        "basis": "point",
                        "sent_at": datetime.now().isoformat(timespec="milliseconds"),
                    }
                )
        return out

    def _model(self, h: int, feature_names: list[str]):
        if h not in self.models:
            self.models[h] = load_model_checked(self.models_dir, f"h{h}_k{self.k}", feature_names)
        return self.models[h]

    def _prune(self, ts: pd.Timestamp) -> None:
        cut = ts - pd.Timedelta(hours=self.history_h + 24)
        for s in self.buf:
            for t in [t for t in self.buf[s] if t < cut]:
                del self.buf[s][t]


def run(
    cfg: dict,
    models_dir: Path,
    db_path: Path,
    host: str,
    port: int,
    k: int,
    stations: list[str],
    neighbors: dict[str, list[str]] | None = None,
    stop: threading.Event | None = None,
    wait_ms: int | None = None,
    keep_log: bool = False,
    pred: OnlinePredictor | None = None,
    thresholds: dict | None = None,
) -> OnlinePredictor:
    """Connect to the broker and predict until `stop` is set (pass `pred` to inspect it live)."""
    stop = stop or threading.Event()
    wait = (wait_ms if wait_ms is not None else cfg["iot"]["predictor_wait_ms"]) / 1000
    pred = pred or OnlinePredictor(
        cfg, models_dir, k, stations, neighbors, wait, keep_log=keep_log, thresholds=thresholds,
        cooldown_h=cfg["warning"]["cooldown_h"],
    )  # fmt: skip
    con = db.connect(db_path)
    client = make_client("predictor")

    def on_message(_c, _u, msg):
        with contextlib.suppress(ValueError):  # invalid payloads: the edge already counts them
            pred.add(Telemetry.from_json(msg.payload))

    client.on_message = on_message
    connect_blocking(client, host, port)
    client.subscribe(topics.EDGE_ALL, qos=topics.EDGE_TELEMETRY.qos)
    try:
        while not stop.is_set():
            for ts in pred.ready():
                rows = pred.predict(ts)
                for row in rows:
                    db.upsert_prediction(con, row)
                for warn in pred.make_warnings(rows):
                    db.upsert_warning(con, warn)
                    msg = WarningMsg(**warn)
                    client.publish(
                        topics.topic(topics.WARNINGS, warn["station"]),
                        msg.to_json(),
                        qos=topics.WARNINGS.qos,
                    )
                con.commit()
            stop.wait(0.02)
    finally:
        disconnect(client)
        con.close()
    return pred


def _load_thresholds(cfg: dict, models_dir: Path, k: int) -> dict | None:
    """Val-chosen deltas of the configured grid for this model (warning_thresholds.json)."""
    path = models_dir / "warning_thresholds.json"
    if not path.exists():
        return None
    method = "M1_lgbm_k0" if k == 0 else f"M2_lgbm_k{k}"
    return (
        json.loads(path.read_text(encoding="utf-8"))
        .get(cfg["warning"]["live_grid"], {})
        .get(method)
    )


def main() -> None:
    from airq.config import load_config
    from airq.env import resolve_paths

    cfg = load_config()
    paths = resolve_paths(cfg["paths"])
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="127.0.0.1:1883")
    ap.add_argument("--k", type=int, default=11)
    ap.add_argument("--db", default=str(paths["db"]))
    args = ap.parse_args()
    host, port = args.broker.rsplit(":", 1)
    neighbors = None
    nb_path = paths["models"] / "neighbors.json"
    if 0 < args.k < len(cfg["data"]["stations"]) - 1:
        neighbors = json.loads(nb_path.read_text(encoding="utf-8"))[f"k{args.k}"]
    thresholds = _load_thresholds(cfg, paths["models"], args.k)
    stop = threading.Event()
    try:
        run(cfg, paths["models"], Path(args.db), host, int(port), args.k,
            cfg["data"]["stations"], neighbors, stop, thresholds=thresholds)  # fmt: skip
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
