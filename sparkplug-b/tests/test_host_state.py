import pysparkplug as spb
from conftest import wait_until

import sparkplugbmcpserver as server

BROKER_HOST = "localhost"
BROKER_PORT = 1883


def test_get_connection_status_reports_host_id():
    status = server.get_connection_status()
    assert status["connected"] is True
    assert status["sparkplug_host_id"] == server.HOST_ID
    assert status["host"] == server.MQTT_HOST
    assert status["port"] == server.MQTT_PORT


def test_set_host_online_publishes_retained_state():
    received: list[spb.State] = []

    def _on_state(_client, message):
        received.append(message.payload)

    server.set_host_online(False)
    server.set_host_online(True)

    watcher = spb.Client()
    state_topic = spb.Topic(message_type=spb.MessageType.STATE, sparkplug_host_id=server.HOST_ID)
    watcher.subscribe(topic=state_topic, qos=spb.QoS.AT_LEAST_ONCE, callback=lambda c, m: _on_state(c, m))
    watcher.connect(BROKER_HOST, port=BROKER_PORT, blocking=False)
    try:
        wait_until(lambda: len(received) >= 1, timeout=10.0)
        assert received[-1].online is True
    finally:
        watcher.disconnect()
