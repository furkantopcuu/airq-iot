"""Pure-Python MQTT broker (amqtt) used when Mosquitto is not installed.

Run: python -m airq.iot.broker [--host 127.0.0.1] [--port 1883]
Local only, anonymous (no auth/TLS: out of scope, see limitations).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import shutil
import socket

from amqtt.broker import Broker


def broker_config(host: str, port: int) -> dict:
    return {
        "listeners": {"default": {"type": "tcp", "bind": f"{host}:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }


def mosquitto_path() -> str | None:
    """Path of the Mosquitto executable if installed (preferred broker), else None."""
    return shutil.which("mosquitto")


def broker_reachable(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


async def serve(host: str, port: int) -> None:
    broker = Broker(broker_config(host, port))
    await broker.start()
    try:
        await asyncio.Event().wait()  # run until cancelled (Ctrl+C)
    finally:
        await broker.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    logging.getLogger("amqtt").setLevel(logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
