"""Thin paho-mqtt 2.x wrapper. Always CallbackAPIVersion.VERSION2 (never mix 1.x signatures)."""

from __future__ import annotations

import threading

import paho.mqtt.client as mqtt


class ConnectError(RuntimeError):
    pass


def make_client(
    client_id: str,
    lwt: tuple[str, str, int, bool] | None = None,
    keepalive_s: int = 30,
) -> mqtt.Client:
    """Create a client. `lwt` = (topic, payload, qos, retain) is the last-will message."""
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client._keepalive_s = keepalive_s  # remembered for connect_blocking()
    if lwt is not None:
        topic, payload, qos, retain = lwt
        client.will_set(topic, payload, qos=qos, retain=retain)
    return client


def connect_blocking(
    client: mqtt.Client, host: str, port: int, timeout_s: float = 10.0
) -> mqtt.Client:
    """Connect, start the network thread and wait for CONNACK (raises ConnectError on timeout)."""
    ready = threading.Event()
    result: dict[str, object] = {}

    def on_connect(_c, _u, _flags, reason_code, _props):
        result["rc"] = reason_code
        ready.set()

    client.on_connect = on_connect
    client.connect(host, port, keepalive=getattr(client, "_keepalive_s", 30))
    client.loop_start()
    if not ready.wait(timeout_s):
        client.loop_stop()
        raise ConnectError(f"No CONNACK from {host}:{port} within {timeout_s}s")
    rc = result["rc"]
    if getattr(rc, "is_failure", False):
        client.loop_stop()
        raise ConnectError(f"Connection refused: {rc}")
    return client


def disconnect(client: mqtt.Client) -> None:
    client.disconnect()
    client.loop_stop()
