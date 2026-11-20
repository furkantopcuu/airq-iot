"""RQ3a: the live system under network stress (spec 6.1). Local, real processes, real broker.

Each run starts a PRIVATE broker and the real services as separate processes (edge gateway, ingest,
predictor, virtual fleet), replays a fixed 14-simulated-day window that contains a large regional
haze, and measures from the SQLite database and from `psutil`:
  PDR, QoS 1 duplicate rate, end-to-end latency (sent_at -> DB and sent_at -> warning),
  throughput, CPU/RAM, forecast RMSE per horizon, warning event recall and false-alarm rate,
  neighbors available.
Network faults are emulated at the application layer (devices/netem.py): a lost reading is
never published, so MQTT's own retransmission cannot save it. Absolute numbers depend on the
machine.
"""

from __future__ import annotations

import ast
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from airq.env import resolve_paths
from airq.eval.metrics import rmse
from airq.iot.broker import broker_reachable, mosquitto_path, start_broker
from airq.server import db
from airq.warning.evaluate import combine_any, false_alarm_stats, matched_leads

HORIZONS = (1, 6, 24)


@dataclass(frozen=True)
class Run:
    plan: str
    speedup: float
    loss: float = 0.0
    delay_ms: float = 0.0
    offline_k: int = 0
    rep: int = 0

    @property
    def key(self) -> str:
        parts = (self.plan, self.speedup, self.loss, self.delay_ms, self.offline_k, self.rep)
        return "|".join(f"{x:g}" if isinstance(x, float) else str(x) for x in parts)


def plan_runs(name: str) -> list[Run]:
    """reduced: about one hour; full: the specified grid; smoke: a plumbing check; offline_fix:
    the offline-device runs repeated after the predictor stopped waiting for offline devices."""
    grid = [(loss, delay) for loss in (0.0, 0.05, 0.10, 0.20) for delay in (0.0, 200.0)]
    if name == "smoke":
        return [Run("smoke", 36000.0, 0.10, 200.0)]
    if name == "full":
        runs = [
            Run("full", sp, lo, de, 0, r)
            for sp in (36000.0, 3600.0)
            for lo, de in grid
            for r in range(3)
        ]
        runs += [Run("full", 36000.0, 0.0, 0.0, k, r) for k in (1, 3, 6) for r in range(3)]
        return runs
    if name == "offline_fix":  # after the predictor stopped waiting for offline devices
        return [Run("offline_fix", 36000.0, 0.0, 0.0, k, r) for k in (0, 1, 3, 6) for r in range(3)]
    if name == "reduced":
        runs = [Run("reduced", 36000.0, lo, de, 0, r) for lo, de in grid for r in range(2)]
        runs += [
            Run("reduced", 3600.0, lo, de, 0, 0)
            for lo, de in ((0.0, 0.0), (0.0, 200.0), (0.10, 0.0), (0.20, 0.0))
        ]
        runs += [Run("reduced", 36000.0, 0.0, 0.0, k, 0) for k in (1, 3, 6)]
        return runs
    raise ValueError(f"unknown plan {name!r}")


def window(cfg: dict, reports: Path, days: int = 14) -> tuple[str, str, pd.Timestamp]:
    """14 simulated days ending 48 h after the onset of the largest test regional haze."""
    ep = pd.read_csv(reports / "tables" / "episodes_test.csv", parse_dates=["start", "end"])
    haze = ep[ep["type"] == "regional_haze"].sort_values(["hours", "peak"], ascending=False)
    onset = haze.iloc[0]["start"]
    end = onset + pd.Timedelta(hours=48)
    start = end - pd.Timedelta(hours=24 * days - 1)
    return str(start), str(end), onset


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Sampler(threading.Thread):
    """Samples CPU% (of one core) and RSS of each service AND all of its child processes.

    On Windows the venv launcher is a thin parent of the real interpreter, so a service is the whole
    process family. Values are summed over the family per sample; RSS is the peak of that sum.
    """

    def __init__(self, procs: dict[str, psutil.Process], period_s: float = 0.5):
        super().__init__(daemon=True)
        self.procs, self.period_s = procs, period_s
        self.stop_flag = threading.Event()
        self.cpu: dict[str, list[float]] = {n: [] for n in procs}
        self.rss: dict[str, float] = {n: 0.0 for n in procs}
        self._seen: dict[tuple[str, int], psutil.Process] = {}

    def _family(self, name: str, root: psutil.Process) -> list[psutil.Process]:
        try:
            members = [root, *root.children(recursive=True)]
        except psutil.Error:
            return []
        out = []
        for m in members:
            key = (name, m.pid)
            if key not in self._seen:
                self._seen[key] = m
                m.cpu_percent(None)  # prime: the first reading of a process is always 0
            out.append(self._seen[key])
        return out

    def run(self) -> None:
        while not self.stop_flag.wait(self.period_s):
            for name, root in self.procs.items():
                cpu = rss = 0.0
                for m in self._family(name, root):
                    try:
                        cpu += m.cpu_percent(None)
                        rss += m.memory_info().rss / 1e6
                    except psutil.Error:
                        pass
                self.cpu[name].append(cpu)
                self.rss[name] = max(self.rss[name], rss)

    def summary(self) -> dict:
        out = {}
        for name in self.procs:
            vals = self.cpu[name] or [0.0]
            out[f"cpu_mean_{name}"] = float(np.mean(vals))
            out[f"cpu_peak_{name}"] = float(np.max(vals))
            out[f"rss_mb_{name}"] = self.rss[name]
        return out


def _spawn(args: list[str], log: Path, env: dict) -> subprocess.Popen:
    fh = log.open("w")
    return subprocess.Popen(
        [sys.executable, "-m", *args], stdout=fh, stderr=subprocess.STDOUT, env=env
    )


def _stations_down(k: int, stations: list[str], seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    return sorted(rng.permutation(stations)[:k].tolist())


def run_one(
    cfg: dict,
    run: Run,
    work: Path,
    start: str,
    end: str,
    onset: pd.Timestamp,
    truth: pd.DataFrame,
    events: pd.DataFrame,
    k_main: int = 11,
    drain_timeout_s: float = 900.0,
    with_predictor: bool = True,
) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    tag = run.key.replace("|", "_")
    db_path, port = work / f"{tag}.db", _free_port()
    for suffix in ("", "-wal", "-shm"):  # a re-run must start from an empty database, never append
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    broker = start_broker("127.0.0.1", port, "auto")
    for _ in range(100):
        if broker_reachable("127.0.0.1", port):
            break
        time.sleep(0.1)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    bk = f"127.0.0.1:{port}"
    procs = {
        "edge": _spawn(["airq.edge.gateway", "--broker", bk], work / f"{tag}.edge.log", env),
        "ingest": _spawn(
            ["airq.server.ingest", "--broker", bk, "--db", str(db_path)],
            work / f"{tag}.ingest.log",
            env,
        ),
    }
    if with_predictor:
        procs["predictor"] = _spawn(
            ["airq.server.predictor", "--broker", bk, "--k", str(k_main), "--db", str(db_path)],
            work / f"{tag}.pred.log",
            env,
        )
    time.sleep(6.0)  # services connect and subscribe before the first reading
    stations = list(cfg["data"]["stations"])
    down = _stations_down(run.offline_k, stations, seed=run.rep) if run.offline_k else []
    fleet_args = [
        "airq.devices.fleet",
        "--start",
        start,
        "--end",
        end,
        "--speedup",
        str(run.speedup),
        "--stations",
        "all",
        "--seed",
        str(run.rep),
        "--broker",
        bk,
    ]
    if run.loss or run.delay_ms:
        fleet_args += ["--netem", f"loss={run.loss},delay={run.delay_ms}"]
    if down:
        fleet_args += ["--offline", ",".join(down)]
    watched = {n: psutil.Process(pr.pid) for n, pr in procs.items()}
    if broker.poll() is None and mosquitto_path():
        watched["broker"] = psutil.Process(broker.pid)
    sampler = _Sampler(watched)
    sampler.start()
    t0 = time.monotonic()
    fleet = subprocess.run(
        [sys.executable, "-m", *fleet_args], capture_output=True, text=True, env=env
    )
    fleet_s = time.monotonic() - t0
    drain_s = _drain(db_path, with_predictor, end, drain_timeout_s)
    sampler.stop_flag.set()
    sampler.join(timeout=3)
    cpu = sampler.summary()
    for pr in procs.values():
        pr.terminate()
    for pr in procs.values():
        try:
            pr.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pr.kill()
    broker.kill()
    attempted = dropped = 0
    try:
        info = ast.literal_eval(fleet.stdout.strip().splitlines()[-1])
        attempted, dropped = int(info["messages"]), int(info["dropped"])
    except (ValueError, SyntaxError, IndexError, KeyError):
        pass
    metrics = _metrics(db_path, truth, events, start, onset, end, attempted, dropped)
    return {
        **asdict(run),
        "key": run.key,
        "k_main": k_main,
        "offline_stations": ",".join(down),
        "sim_start": start,
        "sim_end": end,
        "fleet_wall_s": round(fleet_s, 1),
        "drain_s": round(drain_s, 1),
        **metrics,
        **cpu,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _drain(db_path: Path, with_predictor: bool, end: str, timeout_s: float) -> float:
    """Wait until the services have processed everything the fleet sent (queues drained)."""
    t0 = time.monotonic()
    last, last_change = None, time.monotonic()
    target = pd.Timestamp(end).isoformat()
    while time.monotonic() - t0 < timeout_s:
        time.sleep(2.0)
        if not db_path.exists():
            continue
        try:
            con = db.connect(db_path, read_only=True)
            n = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            m = con.execute("SELECT COALESCE(MAX(made_at_ts), '') FROM predictions").fetchone()[0]
            con.close()
        except Exception:
            continue
        state = (n, m)
        if state != last:
            last, last_change = state, time.monotonic()
        done = (m >= target) if with_predictor else False
        if done or time.monotonic() - last_change > 25.0:
            break
    return time.monotonic() - t0


def _pct(a: list[float], q: float) -> float:
    return float(np.percentile(a, q)) if len(a) else float("nan")


def _metrics(db_path, truth, events, start, onset, end, attempted, dropped) -> dict:
    out: dict = {"attempted": attempted, "dropped_by_netem": dropped}
    if not db_path.exists():
        return out
    con = db.connect(db_path, read_only=True)
    readings = pd.read_sql_query(
        "SELECT station, ts, sent_at, received_at, dup_count FROM readings",
        con,
        parse_dates=["sent_at", "received_at"],
    )
    unique = len(readings)
    out.update(
        unique_delivered=unique,
        pdr=unique / attempted if attempted else float("nan"),
        duplicate_rate=float(readings["dup_count"].sum() / unique) if unique else float("nan"),
    )
    if unique:
        lat = (readings["received_at"] - readings["sent_at"]).dt.total_seconds() * 1000
        span = (readings["received_at"].max() - readings["received_at"].min()).total_seconds()
        out.update(
            lat_db_p50_ms=_pct(lat, 50),
            lat_db_p95_ms=_pct(lat, 95),
            lat_db_p99_ms=_pct(lat, 99),
            throughput_msg_s=unique / span if span > 0 else float("nan"),
        )
    ev = con.execute(
        "SELECT payload FROM system_events WHERE kind='edge_stats' ORDER BY wall_ts DESC LIMIT 1"
    ).fetchone()
    if ev:
        edge = json.loads(ev[0])
        out.update(
            edge_seq_lost=edge.get("seq_lost"),
            edge_invalid=edge.get("invalid"),
            edge_duplicates=edge.get("duplicates"),
            edge_out_of_order=edge.get("out_of_order"),
        )
    preds = pd.read_sql_query(
        "SELECT station, made_at_ts, target_ts, horizon, yhat, n_neighbors FROM predictions",
        con,
        parse_dates=["made_at_ts", "target_ts"],
    )
    warns = pd.read_sql_query(
        "SELECT station, made_at_ts, horizon, threshold, sent_at FROM warnings",
        con,
        parse_dates=["made_at_ts", "sent_at"],
    )
    con.close()
    out["n_predictions"] = len(preds)
    if len(preds):
        out["n_neighbors_mean"] = float(preds["n_neighbors"].mean())
        m = preds.merge(
            truth.rename(columns={"ts": "target_ts"}), on=["station", "target_ts"], how="inner"
        )
        m = m.dropna(subset=["pm25_raw"])
        for h in HORIZONS:
            s = m[m["horizon"] == h]
            out[f"rmse_h{h}"] = rmse(s["pm25_raw"], s["yhat"]) if len(s) else float("nan")
            out[f"n_eval_h{h}"] = int(len(s))
    if len(warns):
        first = readings.groupby("ts")["sent_at"].max()  # the last reading of each hour to arrive
        w = warns.assign(ts=warns["made_at_ts"].dt.strftime("%Y-%m-%dT%H:%M:%S"))
        w["trigger"] = w["ts"].map(first.rename("trigger").to_dict())
        wl = (w["sent_at"] - pd.to_datetime(w["trigger"])).dt.total_seconds() * 1000
        wl = wl[wl.notna()]
        out.update(
            lat_warn_p50_ms=_pct(wl, 50), lat_warn_p95_ms=_pct(wl, 95), lat_warn_p99_ms=_pct(wl, 99)
        )
    out.update(_warning_quality(warns, truth, events, pd.Timestamp(end)))
    return out


def _warning_quality(warns, truth, events, end, stations=None) -> dict:
    """Event recall (horizon-matched, any horizon) and false-alarm rate for theta = 150."""
    res = {"n_alerts_150": 0, "event_recall_150": float("nan"), "false_alarm_150": float("nan")}
    w = warns[warns["threshold"] == 150]
    res["n_alerts_150"] = int(len(w))
    if w.empty:
        return res
    if stations is not None:
        w = w[w["station"].isin(stations)]
        events = events[events["station"].isin(stations)]
    first_pred = w["made_at_ts"].min()
    ev = events[
        (events["type"] == "exceedance")
        & (events["threshold"] == 150)
        & (events["start"] >= first_pred)
        & (events["start"] <= end)
    ]
    per_h = []
    for h in HORIZONS:
        leads: list = []
        for station, sub in ev.groupby("station"):
            times = w[(w["station"] == station) & (w["horizon"] == h)]["made_at_ts"].to_numpy()
            leads += matched_leads(sub["start"], sub["end"], times, h, 24)
        per_h.append(leads)
    if per_h[0]:
        any_leads = combine_any(per_h)
        res["event_recall_150"] = float(np.mean([x is not None for x in any_leads]))
        res["n_events_150"] = len(any_leads)
    fa = tot = 0
    for station, sub in w.groupby("station"):
        t = truth[truth["station"] == station].reset_index(drop=True)
        idx = np.searchsorted(t["ts"].to_numpy(), sub["made_at_ts"].drop_duplicates().to_numpy())
        f, n = false_alarm_stats(idx[idx < len(t)], t["pm25_raw"].to_numpy(dtype=float), 150)
        fa, tot = fa + f, tot + n
    res["false_alarm_150"] = fa / tot if tot else float("nan")
    return res


def env_info(cfg: dict) -> dict:
    mq = mosquitto_path()
    version = None
    if mq:
        try:
            out = subprocess.run([mq, "-h"], capture_output=True, text=True, timeout=10).stdout
            version = out.splitlines()[0] if out else None
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "broker": version or "amqtt (fallback)",
        "note": "everything runs on ONE machine; the sensor->gateway link is emulated at the "
        "application layer; absolute values depend on this machine",
        "created": datetime.now().isoformat(timespec="seconds"),
    }


def run_bench(
    cfg: dict, plan: str, limit: int | None = None, with_predictor: bool = True, sim_days: int = 14
) -> pd.DataFrame:
    """Run (or resume) a plan; every finished run is appended to reports/bench/raw_<plan>.csv."""
    p = resolve_paths(cfg["paths"])
    bench = p["reports"] / "bench"
    bench.mkdir(parents=True, exist_ok=True)
    raw_csv = bench / f"raw_{plan}.csv"
    done = set(pd.read_csv(raw_csv)["key"]) if raw_csv.exists() else set()
    (bench / "env.json").write_text(json.dumps(env_info(cfg), indent=2), encoding="utf-8")
    start, end, onset = window(cfg, p["reports"], sim_days)
    clean = pd.read_parquet(p["processed"] / "clean.parquet", columns=["station", "ts", "pm25_raw"])
    events = pd.read_csv(
        p["reports"] / "tables" / "episodes_test.csv", parse_dates=["start", "end"]
    )
    work = bench / "work"
    todo = [r for r in plan_runs(plan) if r.key not in done]
    for i, run in enumerate(todo[:limit] if limit else todo):
        t0 = time.monotonic()
        row = run_one(
            cfg, run, work, start, end, onset, clean, events, with_predictor=with_predictor
        )
        pd.DataFrame([row]).to_csv(raw_csv, mode="a", header=not raw_csv.exists(), index=False)
        print(
            f"[{i + 1}/{len(todo)}] {run.key} done in {time.monotonic() - t0:.0f}s "
            f"pdr={row.get('pdr', float('nan')):.3f}",
            flush=True,
        )
    return pd.read_csv(raw_csv) if raw_csv.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------------------------
# aggregation: paired comparisons re-read from the per-run databases (fixes three pitfalls)
# ---------------------------------------------------------------------------------------------
def _run_db(work: Path, key: str) -> Path:
    return work / f"{key.replace('|', '_')}.db"


def _read(db_path: Path, sql: str, **kw) -> pd.DataFrame:
    con = db.connect(db_path, read_only=True)
    try:
        return pd.read_sql_query(sql, con, **kw)
    finally:
        con.close()


def paired_rmse(run_db: Path, base_db: Path, truth: pd.DataFrame) -> dict:
    """RMSE of a run and of the lossless baseline on the SAME (station, target, horizon) keys.

    Needed because a run with offline devices predicts for fewer stations: comparing it with the
    baseline over all stations would mix station difficulty into the "damage".
    """
    cols = "station, target_ts, horizon, yhat"
    a = _read(run_db, f"SELECT {cols} FROM predictions", parse_dates=["target_ts"])  # nosec B608
    b = _read(base_db, f"SELECT {cols} FROM predictions", parse_dates=["target_ts"])  # nosec B608
    m = a.merge(b, on=["station", "target_ts", "horizon"], suffixes=("", "_base"))
    m = m.merge(truth.rename(columns={"ts": "target_ts"}), on=["station", "target_ts"])
    m = m.dropna(subset=["pm25_raw"])
    out: dict = {}
    for h in HORIZONS:
        s = m[m["horizon"] == h]
        if len(s):
            out[f"paired_rmse_h{h}"] = rmse(s["pm25_raw"], s["yhat"])
            out[f"paired_rmse_base_h{h}"] = rmse(s["pm25_raw"], s["yhat_base"])
            out[f"paired_delta_h{h}"] = out[f"paired_rmse_h{h}"] - out[f"paired_rmse_base_h{h}"]
            out[f"paired_n_h{h}"] = int(len(s))
    return out


def seq_gaps(run_db: Path) -> int:
    """Readings missing from the per-station seq streams (counted from the database)."""
    r = _read(
        run_db, "SELECT station, MAX(seq) AS mx, COUNT(*) AS n FROM readings GROUP BY station"
    )
    return int((r["mx"] + 1 - r["n"]).clip(lower=0).sum())


BEHIND_DRAIN_S = 60.0  # real-time runs (3600x): a predictor that keeps up drains in about 2 s
BEHIND_FACTOR = 1.25  # offline-device runs: slower than 1.25 x the intact-network median = behind


def predictor_behind(runs: pd.DataFrame) -> pd.Series:
    """True for runs in which the predictor fell behind the arriving data (criteria fixed in
    advance, see docs/KARARLAR.md): 3600x runs that needed > 60 s to drain, and offline-device
    runs whose warning latency exceeds 1.25 x the median of the intact-network runs at that speed.
    (At 36000x the predictor is saturated by design, so only the offline comparison is judged.)"""
    behind = pd.Series(False, index=runs.index)
    if runs["speedup"].nunique() > 1:  # the real-time rule needs a real-time speed in the plan
        slow = runs["speedup"] == runs["speedup"].min()
        behind |= slow & (runs["drain_s"] > BEHIND_DRAIN_S)
    fast = runs["speedup"] == runs["speedup"].max()
    intact = runs[fast & (runs["offline_k"] == 0)]["lat_warn_p50_ms"].median()
    behind |= fast & (runs["offline_k"] > 0) & (runs["lat_warn_p50_ms"] > BEHIND_FACTOR * intact)
    return behind


def aggregate_bench(cfg: dict, plan: str = "reduced") -> pd.DataFrame:
    """Per-configuration table (mean and std over repetitions) -> reports/tables/rq3a_bench.csv."""
    p = resolve_paths(cfg["paths"])
    bench, tables = p["reports"] / "bench", p["reports"] / "tables"
    raw = pd.read_csv(bench / f"raw_{plan}.csv")
    work = bench / "work"
    truth = pd.read_parquet(p["processed"] / "clean.parquet", columns=["station", "ts", "pm25_raw"])
    events = pd.read_csv(
        p["reports"] / "tables" / "episodes_test.csv", parse_dates=["start", "end"]
    )
    stations = list(cfg["data"]["stations"])
    rows = []
    for _, r in raw.iterrows():
        row = r.to_dict()
        dbp = _run_db(work, r["key"])
        base = _run_db(work, f"{plan}|{r['speedup']:g}|0|0|0|0")
        if dbp.exists() and base.exists():
            row.update(paired_rmse(dbp, base, truth))
            row["seq_gaps_db"] = seq_gaps(dbp)
            warns = _read(dbp, "SELECT station, made_at_ts, horizon, threshold FROM warnings",
                          parse_dates=["made_at_ts"])  # fmt: skip
            down = set(str(r.get("offline_stations") or "").split(",")) - {""}
            online = [s for s in stations if s not in down]
            end = pd.Timestamp(r["sim_end"])
            row["event_recall_online_150"] = _warning_quality(warns, truth, events, end, online)[
                "event_recall_150"
            ]
        rows.append(row)
    runs = pd.DataFrame(rows)
    runs["predictor_behind"] = predictor_behind(runs)
    keys = ["speedup", "offline_k", "loss", "delay_ms"]
    num = [c for c in runs.columns if runs[c].dtype.kind in "fi" and c not in keys + ["rep"]]
    g = runs.groupby(keys)
    agg = g[num].mean().add_suffix("_mean").join(g[num].std(ddof=0).add_suffix("_std"))
    agg["reps"] = g.size()
    agg["behind_runs"] = g["predictor_behind"].sum().astype(int)
    # bimodal (kept up ~1 s / fell behind ~115 s): the mean is meaningless, use the median
    agg["lat_warn_p50_ms_median"] = g["lat_warn_p50_ms"].median()
    out = agg.reset_index()
    out.to_csv(
        tables / ("rq3a_bench.csv" if plan == "full" else f"rq3a_bench_{plan}.csv"), index=False
    )
    runs.to_csv(bench / f"runs_{plan}.csv", index=False)
    return out
