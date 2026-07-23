import pytest

import dittomcpserver as server


def _new_connection(name: str) -> dict:
    return {
        "name": name,
        "connectionType": "http-push",
        # closed: validated and stored, but Ditto won't attempt to actually connect.
        "connectionStatus": "closed",
        "uri": "https://example.invalid:443",
        "sources": [],
        "targets": [
            {
                "address": "POST:/",
                "topics": ["_/_/things/twin/events"],
                "authorizationContext": ["nginx:ditto"],
            }
        ],
    }


@pytest.fixture
def connection_id():
    created = server.create_connection(_new_connection("pytest-connection"))
    conn_id = created["id"]
    yield conn_id
    server.devops_client.delete(f"/api/2/connections/{conn_id}")


def test_create_and_get_connection(connection_id):
    fetched = server.get_connection(connection_id)
    assert fetched["id"] == connection_id
    assert fetched["connectionStatus"] == "closed"


def test_list_connections_ids_only(connection_id):
    ids = server.list_connections(ids_only=True)
    assert connection_id in ids


def test_update_connection(connection_id):
    updated = _new_connection("pytest-connection-renamed")
    result = server.update_connection(connection_id, updated)
    assert result["updated"] is True
    assert server.get_connection(connection_id)["name"] == "pytest-connection-renamed"


def test_send_connection_command_rejects_unknown():
    with pytest.raises(ValueError, match="Unsupported command"):
        server.send_connection_command("does-not-matter", "not-a-real-command")


def test_send_connection_command_enable_logs(connection_id):
    server.send_connection_command(connection_id, "connectivity.commands:enableConnectionLogs")
    logs = server.get_connection_logs(connection_id)
    assert "connectionLogs" in logs or isinstance(logs, dict)


def test_get_connection_status_and_metrics(connection_id):
    status = server.get_connection_status(connection_id)
    assert "connectionStatus" in status or isinstance(status, dict)
    metrics = server.get_connection_metrics(connection_id)
    assert isinstance(metrics, dict)


def test_delete_connection_requires_confirm(connection_id):
    with pytest.raises(ValueError, match="confirm"):
        server.delete_connection(connection_id)
    result = server.delete_connection(connection_id, confirm=True)
    assert result["deleted"] is True
