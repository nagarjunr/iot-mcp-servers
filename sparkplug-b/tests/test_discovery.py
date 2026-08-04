import pysparkplug as spb
import pytest
from conftest import wait_until

import sparkplugbmcpserver as server

BROKER_HOST = "localhost"
BROKER_PORT = 1883


@pytest.fixture
def edge_node(unique_id):
    group_id = f"TestGroup-{unique_id}"
    edge_node_id = f"Node-{unique_id}"
    node = spb.EdgeNode(
        group_id=group_id,
        edge_node_id=edge_node_id,
        metrics=[
            spb.Metric(timestamp=spb.get_current_timestamp(), name="Temperature", datatype=spb.DataType.DOUBLE, value=23.5),
        ],
    )
    node.connect(BROKER_HOST, port=BROKER_PORT, blocking=False)
    yield node
    node.disconnect()


def test_node_birth_is_discovered(edge_node):
    wait_until(lambda: server._nodes.get((edge_node.group_id, edge_node.edge_node_id)) is not None)

    result = server.list_edge_nodes(group_id=edge_node.group_id)
    assert result["count"] == 1
    entry = result["edge_nodes"][0]
    assert entry["edge_node_id"] == edge_node.edge_node_id
    assert entry["online"] is True

    metrics = server.get_node_metrics(edge_node.group_id, edge_node.edge_node_id)
    assert metrics["metrics"]["Temperature"]["value"] == 23.5
    assert metrics["metrics"]["Temperature"]["datatype"] == "DOUBLE"


def test_node_data_updates_metrics(edge_node):
    wait_until(lambda: server._nodes.get((edge_node.group_id, edge_node.edge_node_id)) is not None)

    edge_node.update([spb.Metric(timestamp=spb.get_current_timestamp(), name="Temperature", datatype=spb.DataType.DOUBLE, value=99.9)])

    def _updated() -> bool:
        metrics = server.get_node_metrics(edge_node.group_id, edge_node.edge_node_id)
        return metrics["metrics"]["Temperature"]["value"] == 99.9

    wait_until(_updated)


def test_node_death_marks_offline(edge_node):
    wait_until(lambda: server._nodes.get((edge_node.group_id, edge_node.edge_node_id)) is not None)
    edge_node.disconnect()

    def _offline() -> bool:
        node = server._nodes.get((edge_node.group_id, edge_node.edge_node_id))
        return node is not None and node.online is False

    wait_until(_offline)


def test_device_birth_is_discovered(edge_node, unique_id):
    wait_until(lambda: server._nodes.get((edge_node.group_id, edge_node.edge_node_id)) is not None)

    device_id = f"Device-{unique_id}"
    device = spb.Device(
        device_id=device_id,
        metrics=[
            spb.Metric(timestamp=spb.get_current_timestamp(), name="Pressure", datatype=spb.DataType.FLOAT, value=1.2),
        ],
    )
    edge_node.register(device)

    wait_until(lambda: server._devices.get((edge_node.group_id, edge_node.edge_node_id, device_id)) is not None)

    result = server.list_devices(group_id=edge_node.group_id, edge_node_id=edge_node.edge_node_id)
    assert result["count"] == 1
    assert result["devices"][0]["device_id"] == device_id

    metrics = server.get_device_metrics(edge_node.group_id, edge_node.edge_node_id, device_id)
    assert metrics["metrics"]["Pressure"]["value"] == pytest.approx(1.2, abs=1e-5)
    assert metrics["metrics"]["Pressure"]["datatype"] == "FLOAT"


def test_get_node_metrics_unknown_raises():
    with pytest.raises(ValueError, match="Unknown edge node"):
        server.get_node_metrics("NoSuchGroup", "NoSuchNode")


def test_get_device_metrics_unknown_raises():
    with pytest.raises(ValueError, match="Unknown device"):
        server.get_device_metrics("NoSuchGroup", "NoSuchNode", "NoSuchDevice")
