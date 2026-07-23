import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent

# Must be set before any test module imports dittomcpserver, since the module
# reads DITTO_BASE_URL at import time.
os.environ.setdefault("DITTO_BASE_URL", "http://localhost:8080")
os.environ.setdefault("DITTO_USERNAME", "ditto")
os.environ.setdefault("DITTO_PASSWORD", "ditto")
os.environ.setdefault("DITTO_DEVOPS_USERNAME", "devops")
os.environ.setdefault("DITTO_DEVOPS_PASSWORD", "foobar")


def _wait_for_gateway(url: str, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code < 500:
                return
        except httpx.HTTPError as e:
            last_error = e
        time.sleep(2.0)
    raise RuntimeError(f"Eclipse Ditto stack did not become ready in time: {last_error}")


@pytest.fixture(scope="session", autouse=True)
def ditto_stack():
    """Bring up the real Eclipse Ditto docker-compose stack for the test session."""
    subprocess.run(["docker", "compose", "up", "-d"], cwd=SERVER_DIR, check=True)
    _wait_for_gateway(f"{os.environ['DITTO_BASE_URL']}/health")
    yield
    subprocess.run(["docker", "compose", "down"], cwd=SERVER_DIR, check=True)
