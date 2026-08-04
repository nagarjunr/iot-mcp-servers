import os
import socket
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent

# Must be set before any test module imports sparkplugbmcpserver, since the
# module connects to the broker at import time.
os.environ.setdefault("SPARKPLUG_MQTT_HOST", "localhost")
os.environ.setdefault("SPARKPLUG_MQTT_PORT", "1883")
os.environ.setdefault("SPARKPLUG_HOST_ID", "pytest-host")


def _wait_for_port(host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as e:
            last_error = e
        time.sleep(1.0)
    raise RuntimeError(f"Mosquitto did not become reachable on {host}:{port} in time: {last_error}")


def pytest_configure(config):
    """Bring up the real Mosquitto docker-compose stack before test collection.

    Unlike a fixture (which only runs once a test actually executes),
    sparkplugbmcpserver connects to the broker eagerly at import time -- and
    pytest imports every test module during collection, before any fixture
    runs. The stack must therefore be up before that import happens.
    """
    subprocess.run(["docker", "compose", "up", "-d"], cwd=SERVER_DIR, check=True)
    _wait_for_port(os.environ["SPARKPLUG_MQTT_HOST"], int(os.environ["SPARKPLUG_MQTT_PORT"]))


def pytest_unconfigure(config):
    subprocess.run(["docker", "compose", "down"], cwd=SERVER_DIR, check=True)


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0, interval: float = 0.1) -> None:
    """Poll a predicate until it's True or raise on timeout.

    Sparkplug traffic between the simulated edge node fixtures and this
    server's client both round-trip through a real Mosquitto broker, so
    state updates are asynchronous with respect to the test thread.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


@pytest.fixture
def unique_id() -> str:
    return uuid.uuid4().hex[:8]
