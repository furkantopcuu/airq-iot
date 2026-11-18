import socket
import subprocess
import sys
import time

import pytest

from airq.iot.broker import broker_reachable


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def broker():
    """Start a private amqtt broker on a free port for tests marked `broker`."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "airq.iot.broker", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not broker_reachable("127.0.0.1", port):
            if proc.poll() is not None:
                pytest.skip("amqtt broker failed to start")
            time.sleep(0.2)
        if not broker_reachable("127.0.0.1", port):
            pytest.skip("amqtt broker did not become reachable")
        yield "127.0.0.1", port
    finally:
        proc.kill()
        proc.wait(timeout=10)
