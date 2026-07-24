import os
import socket
import subprocess
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent

# Must be set before any test module imports mqttmcpserver, since the module
# connects to the broker at import time.
os.environ.setdefault("MQTT_HOST", "localhost")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USERNAME", "mqtt")
os.environ.setdefault("MQTT_PASSWORD", "mqtt")


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
    mqttmcpserver connects to the broker eagerly at import time -- and pytest
    imports every test module during collection, before any fixture runs. The
    stack must therefore be up before that import happens.
    """
    subprocess.run(["docker", "compose", "up", "-d"], cwd=SERVER_DIR, check=True)
    _wait_for_port(os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"]))
    _wait_for_port(os.environ["MQTT_HOST"], 8883)


def pytest_unconfigure(config):
    subprocess.run(["docker", "compose", "down"], cwd=SERVER_DIR, check=True)
