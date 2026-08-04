import pysparkplug as spb
import pytest
from conftest import wait_until

import sparkplugbmcpserver as server

BROKER_HOST = "localhost"
BROKER_PORT = 1883


@pytest.fixture
def edge_node(unique_id):
    group_id = f"WatchGroup-{unique_id}"
    edge_node_id = f"WatchNode-{unique_id}"
    node = spb.EdgeNode(
        group_id=group_id,
        edge_node_id=edge_node_id,
        metrics=[spb.Metric(timestamp=spb.get_current_timestamp(), name="Level", datatype=spb.DataType.INT32, value=1)],
    )
    yield node
    node.disconnect()


def test_watch_captures_birth_and_data(edge_node):
    watch = server.start_watch(group_id=edge_node.group_id, edge_node_id=edge_node.edge_node_id)
    session_id = watch["session_id"]
    try:
        edge_node.connect(BROKER_HOST, port=BROKER_PORT, blocking=False)

        result = server.get_events(session_id, timeout_seconds=5.0)
        assert result["count"] >= 1
        birth_events = [e for e in result["events"] if e["message_type"] == "NBIRTH"]
        assert len(birth_events) == 1
        assert birth_events[0]["metrics"][0]["name"] == "Level"

        edge_node.update([spb.Metric(timestamp=spb.get_current_timestamp(), name="Level", datatype=spb.DataType.INT32, value=2)])

        def _got_data() -> bool:
            drained = server.get_events(session_id, timeout_seconds=0.5)
            return any(e["message_type"] == "NDATA" for e in drained["events"])

        wait_until(_got_data, timeout=10.0)
    finally:
        server.stop_watch(session_id)


def test_watch_filters_by_message_type(edge_node):
    watch = server.start_watch(
        group_id=edge_node.group_id,
        edge_node_id=edge_node.edge_node_id,
        message_types=["NDATA"],
    )
    session_id = watch["session_id"]
    try:
        edge_node.connect(BROKER_HOST, port=BROKER_PORT, blocking=False)
        wait_until(lambda: server._nodes.get((edge_node.group_id, edge_node.edge_node_id)) is not None)

        result = server.get_events(session_id, timeout_seconds=1.0)
        assert all(e["message_type"] == "NDATA" for e in result["events"])
        assert not any(e["message_type"] == "NBIRTH" for e in result["events"])
    finally:
        server.stop_watch(session_id)


def test_start_watch_rejects_invalid_message_type():
    with pytest.raises(ValueError, match="Invalid message_types"):
        server.start_watch(message_types=["NOT_A_TYPE"])


def test_stop_watch_unknown_session_raises():
    with pytest.raises(ValueError, match="No such watch session"):
        server.stop_watch("does-not-exist")


def test_list_watches_reflects_active_sessions():
    watch = server.start_watch()
    session_id = watch["session_id"]
    try:
        result = server.list_watches()
        assert any(s["session_id"] == session_id for s in result["sessions"])
    finally:
        server.stop_watch(session_id)
