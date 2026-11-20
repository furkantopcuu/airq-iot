"""One-command demo stack (spec 12.2): broker check, edge, ingest, predictor, fleet, API, dashboard.

python -m scripts.demo                 full live demo (real data, trained models)
python -m scripts.demo --offline       dashboard + API on a recorded SQLite file, no broker needed
python -m scripts.demo --smoke         10-second end-to-end self test (used by the tests)

Everything runs as separate processes (as in a real deployment); Ctrl+C stops all of them.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import psutil

from airq.devices.modes import HOUR
from airq.env import repo_root, resolve_paths
from airq.iot.broker import broker_reachable, start_broker
from airq.iot.schemas import FleetControl
from airq.pipelines.scenarios import sim_clock
from airq.server.control import Controller

GUIDE = """
Demo hazır. Tarayıcıda Senaryo Kontrol + Canlı izleme sayfasını aç: {dash}
 A) Planlı akış (~3 dk): sol panelde "Hazır senaryolar" -> sırayla
{flow}
 B) Serbest test: "Müdahale (cihaz)" bölümünden istasyon ve değer seç, "Müdahaleyi gönder".
 "Her şeyi sıfırla" her zaman temiz duruma döner. Ctrl+C her şeyi kapatır.
"""
OFFLINE_NOTE = (
    "Çevrimdışı kip: kayıtlı veritabanı gösteriliyor; broker yok, bu yüzden kontrol paneli komut "
    "gönderemez (503). Grafikler, kartlar ve puan tablosu çalışır."
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def wait_for(cond, timeout_s: float, every_s: float = 0.25) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001 - not ready yet
            pass
        time.sleep(every_s)
    return False


def pick_recorded_db(explicit: str | None, cfg: dict) -> Path | None:
    """The database for --offline: the given one, else the demo run's, else a scenario run's."""
    if explicit:
        return Path(explicit)
    paths = resolve_paths(cfg["paths"])
    candidates = [paths["db"].parent / "demo.db", paths["db"]]
    work = paths["reports"] / "scenarios" / "work"
    if work.exists():
        candidates += sorted(work.glob("gercek_haze_replay.db")) + sorted(work.glob("*.db"))
    return next((c for c in candidates if c.exists() and c.stat().st_size > 0), None)


class Stack:
    """Subprocess group with log files and a clean (tree-wide) shutdown."""

    def __init__(self, log_dir: Path, env: dict | None = None):
        self.log_dir = log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
        self.procs: dict[str, subprocess.Popen] = {}
        self._logs: list = []

    def spawn(self, name: str, args: list[str], env: dict | None = None) -> subprocess.Popen:
        log = open(self.log_dir / f"{name}.log", "w", encoding="utf-8")  # noqa: SIM115
        self._logs.append(log)
        proc = subprocess.Popen(
            [sys.executable, "-m", *args], cwd=repo_root(), env={**self.env, **(env or {})},
            stdout=log, stderr=subprocess.STDOUT,
        )  # fmt: skip
        self.procs[name] = proc
        return proc

    def alive(self, name: str) -> bool:
        return self.procs[name].poll() is None

    def stop(self) -> None:
        for proc in self.procs.values():
            tree = []
            with contextlib.suppress(psutil.Error):
                tree = psutil.Process(proc.pid).children(recursive=True)
            proc.terminate()
            for child in tree:
                with contextlib.suppress(psutil.Error):
                    child.terminate()
        deadline = time.monotonic() + 10
        for proc in self.procs.values():
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
        for log in self._logs:
            log.close()


def api_args(port: int) -> list[str]:
    return ["uvicorn", "airq.server.api:app", "--host", "127.0.0.1", "--port", str(port),
            "--log-level", "warning"]  # fmt: skip


def dashboard_args(port: int) -> list[str]:
    app = repo_root() / "src" / "airq" / "dashboard" / "app.py"
    return ["streamlit", "run", str(app), "--server.port", str(port), "--server.headless", "true",
            "--browser.gatherUsageStats", "false"]  # fmt: skip


def fleet_args(
    start: str, end: str, speedup: float, broker: str, stations: str = "all"
) -> list[str]:
    return ["airq.devices.fleet", "--start", start, "--end", end, "--speedup", str(speedup),
            "--stations", stations, "--broker", broker, "--control"]  # fmt: skip


def flow_text(names: list[str]) -> str:
    return "\n".join(f"    {i}. {n}" for i, n in enumerate(names, 1))


def ensure_broker(host: str, port: int, stack_cleanup: list) -> str:
    """Use a running broker on host:port, else start one (Mosquitto if installed, else amqtt)."""
    if broker_reachable(host, port):
        print(f"MQTT broker bulundu: {host}:{port}")
        return f"{host}:{port}"
    proc = start_broker(host, port, "auto")
    stack_cleanup.append(proc)
    if not wait_for(lambda: broker_reachable(host, port), 20):
        raise SystemExit("MQTT broker başlatılamadı (Mosquitto kurulu mu? bkz. README).")
    print(f"MQTT broker başlatıldı: {host}:{port}")
    return f"{host}:{port}"


def run_demo(cfg: dict, args) -> int:
    d, iot = cfg["demo"], cfg["iot"]["broker"]
    paths = resolve_paths(cfg["paths"])
    api_port, dash_port = args.api_port or d["api_port"], args.dashboard_port or d["dashboard_port"]
    logs = paths["db"].parent / "demo_logs"
    extra: list = []
    stack = Stack(logs)
    try:
        if args.offline:
            db_path = pick_recorded_db(args.db, cfg)
            if db_path is None:
                raise SystemExit(
                    "Kayıtlı veritabanı yok: önce canlı demo ya da run_scenarios çalıştır."
                )
            broker = f"{iot['host']}:{free_port()}"  # nothing listens: control answers 503
            print(OFFLINE_NOTE, f"\nVeritabanı: {db_path}")
        else:
            db_path = Path(args.db) if args.db else paths["db"].parent / "demo.db"
            if not args.keep_db:
                for suffix in ("", "-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
            broker = ensure_broker(iot["host"], int(args.port or iot["port"]), extra)
        env = {"AIRQ_DB": str(db_path), "AIRQ_BROKER": broker,
               "AIRQ_API_URL": f"http://127.0.0.1:{api_port}"}  # fmt: skip
        stack.env.update(env)
        if not args.offline:
            stack.spawn("edge", ["airq.edge.gateway", "--broker", broker])
            stack.spawn("ingest", ["airq.server.ingest", "--broker", broker, "--db", str(db_path)])
            if not args.no_predictor:
                stack.spawn("predictor", ["airq.server.predictor", "--broker", broker, "--db",
                                          str(db_path)])  # fmt: skip
        stack.spawn("api", api_args(api_port))
        if not wait_for(
            lambda: httpx.get(f"http://127.0.0.1:{api_port}/health").status_code == 200, 30
        ):
            raise SystemExit(f"API açılmadı; log: {logs / 'api.log'}")
        if not args.no_dashboard:
            stack.spawn("dashboard", dashboard_args(dash_port))
            if not wait_for(lambda: port_open("127.0.0.1", dash_port), 45):
                raise SystemExit(f"Dashboard açılmadı; log: {logs / 'dashboard.log'}")
        dash_url = f"http://127.0.0.1:{dash_port}"
        if not args.offline:
            time.sleep(4.0)  # services subscribe before the first reading
            stack.spawn("fleet", fleet_args(d["start"], d["end"], d["warmup_speedup"], broker))
            switch_to_demo_speed(cfg, db_path, broker, stack)
        print(GUIDE.format(dash=dash_url, flow=flow_text(d["scenario_flow"])))
        if not args.no_browser:
            webbrowser.open(dash_url)
        deadline = None if not args.duration else time.monotonic() + args.duration
        while True:
            time.sleep(1.0)
            if deadline is not None and time.monotonic() > deadline:
                print("Süre doldu, kapatılıyor.")
                return 0
            dead = [n for n in ("api", "dashboard") if n in stack.procs and not stack.alive(n)]
            if dead:
                print(f"{dead} beklenmedik şekilde durdu; loglar: {logs}")
                return 1
            if not args.offline and not stack.alive("fleet"):
                print("Filo (veri tekrarı) bitti; arayüz açık kalıyor, Ctrl+C ile çık.")
                while deadline is None or time.monotonic() < deadline:
                    time.sleep(1.0)
                return 0
    except KeyboardInterrupt:
        print("\nKapatılıyor ...")
        return 0
    finally:
        stack.stop()
        for proc in extra:
            proc.terminate()


def switch_to_demo_speed(cfg: dict, db_path: Path, broker: str, stack: Stack) -> None:
    """Drop the fleet from warm-up speed to demo speed once the warm-up hours are played.

    Runs in a background thread so the main loop stays responsive."""
    d = cfg["demo"]
    zero = pd.Timestamp(d["start"]) + d["warmup_h"] * HOUR

    def work():
        clock = sim_clock(db_path)
        host, _, port = broker.rpartition(":")
        ctl = Controller(host, int(port), client_id="demo-speed")
        try:
            ctl.start()
            while stack.alive("fleet"):
                now = clock()
                if now is not None and now >= zero:
                    msg = FleetControl(
                        cmd_id=f"demo-speed-{int(time.time())}", issued_at=datetime.now(),
                        action="speedup", value=float(d["speedup"]), label="demo-speed",
                    )  # fmt: skip
                    ctl.send(msg)
                    print(f"Isınma bitti ({now}); hız {d['speedup']}× olarak ayarlandı.")
                    return
                time.sleep(0.5)
        finally:
            ctl.stop()

    threading.Thread(target=work, name="demo-speed", daemon=True).start()


def smoke(cfg: dict, hours: int = 10, speedup: float = 3600.0) -> dict:
    """Real processes, private broker, a command through the HTTP API: does everything connect?"""
    paths = resolve_paths(cfg["paths"])
    work = paths["reports"] / "scenarios" / "work" / "smoke"
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "smoke.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    port, api_port = free_port(), free_port()
    broker_proc = start_broker("127.0.0.1", port, "auto")
    bk = f"127.0.0.1:{port}"
    stack = Stack(work, {"AIRQ_DB": str(db_path), "AIRQ_BROKER": bk,
                         "AIRQ_API_URL": f"http://127.0.0.1:{api_port}"})  # fmt: skip
    result: dict = {"ok": False}
    try:
        if not wait_for(lambda: broker_reachable("127.0.0.1", port), 20):
            raise RuntimeError("broker did not start")
        stack.spawn("edge", ["airq.edge.gateway", "--broker", bk])
        stack.spawn("ingest", ["airq.server.ingest", "--broker", bk, "--db", str(db_path)])
        stack.spawn("api", api_args(api_port))
        base = f"http://127.0.0.1:{api_port}"
        if not wait_for(lambda: httpx.get(f"{base}/health").status_code == 200, 30):
            raise RuntimeError("API did not start")
        time.sleep(4.0)
        start = pd.Timestamp(cfg["split"]["test"][0])
        end = start + (hours - 1) * HOUR
        stack.spawn("fleet", fleet_args(str(start), str(end), speedup, bk, "Dongsi,Huairou"))
        if not wait_for(lambda: len(httpx.get(f"{base}/stations").json()) == 2, 30):
            raise RuntimeError("stations never appeared in the database")
        body = {"target": "Dongsi", "variables": ["pm25"], "mode": "manual",
                "params": {"value": 300}, "duration_h": 3, "label": "smoke"}  # fmt: skip
        resp = httpx.post(f"{base}/control/device", json=body, timeout=10)
        result["command_status"], result["command_ok"] = resp.status_code, resp.json().get("ok")
        stack.procs["fleet"].wait(timeout=60)
        if not wait_for(lambda: _count_300(base) >= 1, 15):
            raise RuntimeError("the intervention never showed up in the database")
        active = httpx.get(f"{base}/control/active").json()
        result["active_interventions"] = len(active["interventions"])
        result["readings_300"] = _count_300(base)
        result["ok"] = result["command_status"] == 200 and bool(result["command_ok"])
    finally:
        stack.stop()
        broker_proc.terminate()
    return result


def _count_300(base: str) -> int:
    """Readings that show the intervention: the value 300 itself, or the edge filter's `rate_jump`
    flag (an instant jump to 300 is exactly what the edge is built to catch and null out)."""
    rows = httpx.get(f"{base}/readings/Dongsi", params={"hours": 48}).json()
    return sum(1 for r in rows if r["pm25"] == 300.0 or "rate_jump" in r["quality_flags"])
