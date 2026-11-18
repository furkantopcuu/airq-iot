"""MQTT broker helpers: Mosquitto (preferred, reference broker) or pure-Python amqtt (fallback).

Run: python -m airq.iot.broker [--kind auto|mosquitto|amqtt] [--host 127.0.0.1] [--port 1883]
Local only, anonymous (no auth/TLS: out of scope, see limitations).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS_MOSQUITTO = Path(r"C:\Program Files\mosquitto\mosquitto.exe")


def broker_config(host: str, port: int) -> dict:
    """amqtt configuration."""
    return {
        "listeners": {"default": {"type": "tcp", "bind": f"{host}:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }


def mosquitto_path() -> str | None:
    """Path of the Mosquitto executable if installed (preferred broker), else None."""
    found = shutil.which("mosquitto")
    if found:
        return found
    return str(WINDOWS_MOSQUITTO) if WINDOWS_MOSQUITTO.exists() else None


def mosquitto_conf_text(host: str, port: int) -> str:
    return f"listener {port} {host}\nallow_anonymous true\npersistence false\nlog_type error\n"


def broker_reachable(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def resolve_kind(kind: str = "auto") -> str:
    kind = os.environ.get("AIRQ_BROKER", kind)
    if kind == "auto":
        return "mosquitto" if mosquitto_path() else "amqtt"
    if kind == "mosquitto" and not mosquitto_path():
        raise RuntimeError("Mosquitto is not installed")
    return kind


def start_broker(host: str, port: int, kind: str = "auto") -> subprocess.Popen:
    """Start a private broker process on host:port and return it (caller kills it)."""
    kind = resolve_kind(kind)
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if kind == "mosquitto":
        conf = Path(tempfile.mkdtemp(prefix="airq-mosq-")) / "mosquitto.conf"
        conf.write_text(mosquitto_conf_text(host, port), encoding="utf-8")
        return subprocess.Popen([mosquitto_path(), "-c", str(conf)], **quiet)
    cmd = [sys.executable, "-m", "airq.iot.broker", "--kind", "amqtt", "--host", host]
    return subprocess.Popen([*cmd, "--port", str(port)], **quiet)


async def serve_amqtt(host: str, port: int) -> None:
    from amqtt.broker import Broker  # imported lazily: only needed for the fallback broker

    broker = Broker(broker_config(host, port))
    await broker.start()
    try:
        await asyncio.Event().wait()  # run until cancelled (Ctrl+C)
    finally:
        await broker.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="auto", choices=["auto", "mosquitto", "amqtt"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    kind = resolve_kind(args.kind)
    if kind == "mosquitto":
        proc = start_broker(args.host, args.port, "mosquitto")
        with contextlib.suppress(KeyboardInterrupt):
            proc.wait()
        proc.kill()
        return
    logging.getLogger("amqtt").setLevel(logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve_amqtt(args.host, args.port))


if __name__ == "__main__":
    main()
