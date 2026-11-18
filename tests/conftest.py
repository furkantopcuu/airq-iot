import socket
import time

import pytest

from airq.iot.broker import broker_reachable, mosquitto_path, start_broker


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", params=["amqtt", "mosquitto"])
def broker(request):
    """A private broker on a free port; tests marked `broker` run on every available broker."""
    kind = request.param
    if kind == "mosquitto" and not mosquitto_path():
        pytest.skip("Mosquitto is not installed")
    port = _free_port()
    proc = start_broker("127.0.0.1", port, kind)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not broker_reachable("127.0.0.1", port):
            if proc.poll() is not None:
                pytest.skip(f"{kind} broker failed to start")
            time.sleep(0.2)
        if not broker_reachable("127.0.0.1", port):
            pytest.skip(f"{kind} broker did not become reachable")
        yield "127.0.0.1", port
    finally:
        proc.kill()
        proc.wait(timeout=10)
