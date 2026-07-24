import os
import subprocess
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent


def test_tls_connection_and_publish():
    # mqttmcpserver connects at import time, so testing the TLS (8883) listener
    # alongside the plain (1883) listener used by the rest of the suite needs
    # a separate process rather than a second import in this one.
    script = (
        "import mqttmcpserver as s\n"
        "status = s.get_connection_status()\n"
        "assert status['connected'] is True, status\n"
        "result = s.publish_message('pytest/tls-check', 'secure-hello', qos=1)\n"
        "assert result['acknowledged'] is True, result\n"
        "print('TLS_OK')\n"
    )
    env = {
        **os.environ,
        "MQTT_HOST": "localhost",
        "MQTT_PORT": "8883",
        "MQTT_USERNAME": "mqtt",
        "MQTT_PASSWORD": "mqtt",
        "MQTT_USE_TLS": "true",
        "MQTT_TLS_CA_CERTS": str(SERVER_DIR / "docker" / "certs" / "ca.crt"),
    }
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "TLS_OK" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
