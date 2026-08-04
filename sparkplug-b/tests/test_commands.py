import threading

import pysparkplug as spb
import pytest
from conftest import wait_until

import sparkplugbmcpserver as server

BROKER_HOST = "localhost"
BROKER_PORT = 1883


@pytest.fixture
def edge_node_with_capture(unique_id):
    received: list[spb.Message] = []
    lock = threading.Lock()

    def _capture(_node, message):
        with lock:
            received.append(message)

    group_id = f"CmdGroup-{unique_id}"
    edge_node_id = f"CmdNode-{unique_id}"
    node = spb.EdgeNode(
        group_id=group_id,
        edge_node_id=edge_node_id,
        metrics=[spb.Metric(timestamp=spb.get_current_timestamp(), name="Setpoint", datatype=spb.DataType.DOUBLE, value=0.0)],
        cmd_callback=_capture,
    )
    node.connect(BROKER_HOST, port=BROKER_PORT, blocking=False)
    node.received = received  # type: ignore[attr-defined]
    node.received_lock = lock  # type: ignore[attr-defined]
    yield node
    node.disconnect()


def test_send_node_command_round_trip(edge_node_with_capture):
    node = edge_node_with_capture
    wait_until(lambda: server._nodes.get((node.group_id, node.edge_node_id)) is not None)

    result = server.send_node_command(
        node.group_id,
        node.edge_node_id,
        [{"name": "Setpoint", "datatype": "DOUBLE", "value": 42.5}],
    )
    assert result["metrics_sent"] == ["Setpoint"]

    wait_until(lambda: len(node.received) >= 1)  # type: ignore[attr-defined]
    with node.received_lock:  # type: ignore[attr-defined]
        message = node.received[0]  # type: ignore[attr-defined]
    metric = message.payload.metrics[0]
    assert metric.name == "Setpoint"
    assert metric.value == 42.5
    assert metric.datatype == spb.DataType.DOUBLE


def test_request_node_rebirth_sends_control_metric(edge_node_with_capture):
    node = edge_node_with_capture
    wait_until(lambda: server._nodes.get((node.group_id, node.edge_node_id)) is not None)

    server.request_node_rebirth(node.group_id, node.edge_node_id)

    wait_until(lambda: len(node.received) >= 1)  # type: ignore[attr-defined]
    with node.received_lock:  # type: ignore[attr-defined]
        message = node.received[0]  # type: ignore[attr-defined]
    metric = message.payload.metrics[0]
    assert metric.name == "Node Control/Rebirth"
    assert metric.value is True


def test_send_device_command_round_trip(edge_node_with_capture, unique_id):
    node = edge_node_with_capture
    wait_until(lambda: server._nodes.get((node.group_id, node.edge_node_id)) is not None)

    received: list[spb.Message] = []
    device_lock = threading.Lock()

    def _capture_device(_node, message):
        with device_lock:
            received.append(message)

    device_id = f"CmdDevice-{unique_id}"
    device = spb.Device(
        device_id=device_id,
        metrics=[spb.Metric(timestamp=spb.get_current_timestamp(), name="Valve", datatype=spb.DataType.BOOLEAN, value=False)],
        cmd_callback=_capture_device,
    )
    node.register(device)
    wait_until(lambda: server._devices.get((node.group_id, node.edge_node_id, device_id)) is not None)

    result = server.send_device_command(
        node.group_id,
        node.edge_node_id,
        device_id,
        [{"name": "Valve", "datatype": "BOOLEAN", "value": True}],
    )
    assert result["metrics_sent"] == ["Valve"]

    wait_until(lambda: len(received) >= 1)
    with device_lock:
        message = received[0]
    metric = message.payload.metrics[0]
    assert metric.name == "Valve"
    assert metric.value is True


def test_send_node_command_rejects_unsupported_datatype(edge_node_with_capture):
    node = edge_node_with_capture
    with pytest.raises(ValueError, match="Unsupported or invalid Sparkplug datatype"):
        server.send_node_command(node.group_id, node.edge_node_id, [{"name": "X", "datatype": "TEMPLATE", "value": 1}])
