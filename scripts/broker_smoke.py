"""Preflight: pub/sub round trip against the broker (python -m scripts.broker_smoke)."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import uuid

from airq.iot.broker import broker_reachable, mosquitto_path
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="127.0.0.1:1883")
    args = ap.parse_args()
    host, port = args.broker.rsplit(":", 1)
    port = int(port)
    if not broker_reachable(host, port):
        print(f"FAIL: nothing is listening on {host}:{port}")
        return 1
    got: list[bytes] = []
    sub = make_client(f"smoke-sub-{uuid.uuid4().hex[:8]}")
    sub.on_message = lambda _c, _u, m: got.append(m.payload)
    subscribed = threading.Event()
    sub.on_subscribe = lambda *_a, **_k: subscribed.set()
    connect_blocking(sub, host, port)
    sub.subscribe("airq/smoke", qos=1)
    if not subscribed.wait(5):  # wait for the broker's SUBACK, not a fixed sleep
        print("FAIL: subscription was not acknowledged")
        return 1
    pub = make_client(f"smoke-pub-{uuid.uuid4().hex[:8]}")
    connect_blocking(pub, host, port)
    t0 = time.monotonic()
    pub.publish("airq/smoke", "ping", qos=1).wait_for_publish(5)
    deadline = time.monotonic() + 5
    while not got and time.monotonic() < deadline:
        time.sleep(0.01)
    rtt_ms = (time.monotonic() - t0) * 1000
    disconnect(pub)
    disconnect(sub)
    if got != [b"ping"]:
        print("FAIL: message not received")
        return 1
    print(
        f"OK: pub/sub round trip {rtt_ms:.1f} ms on {host}:{port} (mosquitto: {mosquitto_path()})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
