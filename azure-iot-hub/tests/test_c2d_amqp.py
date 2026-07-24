import os

import pytest
from fake_amqp_hub import FakeHubServer

import azureiothubmcpserver as server

PORT = 25671


@pytest.fixture(scope="module")
def fake_hub():
    hub = FakeHubServer(port=PORT)
    hub.start()
    os.environ["AZURE_IOT_HUB_AMQP_HOSTNAME_OVERRIDE"] = "127.0.0.1"
    os.environ["AZURE_IOT_HUB_AMQP_PORT"] = str(PORT)
    os.environ["AZURE_IOT_HUB_AMQP_USE_TLS"] = "false"
    yield hub
    hub.stop()
    del os.environ["AZURE_IOT_HUB_AMQP_HOSTNAME_OVERRIDE"]
    del os.environ["AZURE_IOT_HUB_AMQP_PORT"]
    del os.environ["AZURE_IOT_HUB_AMQP_USE_TLS"]


@pytest.fixture(autouse=True)
def _clear_received(fake_hub):
    fake_hub.handler.received_devicebound_messages.clear()
    yield


def test_send_c2d_message_round_trip(fake_hub):
    result = server.send_c2d_message(
        "pytest-device",
        "hello",
        content_type="text/plain",
        correlation_id="corr-1",
        app_properties={"source": "pytest"},
    )
    assert result == {"deviceId": "pytest-device", "sent": True}

    received = fake_hub.handler.received_devicebound_messages
    assert len(received) == 1
    msg = received[0]
    assert msg.address == "/devices/pytest-device/messages/devicebound"
    assert msg.body == "hello"
    assert msg.content_type == "text/plain"
    assert msg.correlation_id == "corr-1"
    assert dict(msg.properties) == {"source": "pytest"}


def test_send_c2d_message_without_optional_fields(fake_hub):
    server.send_c2d_message("pytest-device-2", "just a payload")
    received = fake_hub.handler.received_devicebound_messages
    assert len(received) == 1
    assert received[0].body == "just a payload"
