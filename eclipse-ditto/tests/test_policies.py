import pytest

import dittomcpserver as server

POLICY_ID = "org.eclipse.ditto:pytest-policy"


def _entry(subject: str = "nginx:ditto") -> dict:
    return {
        "subjects": {subject: {"type": "generated"}},
        "resources": {
            "thing:/": {"grant": ["READ", "WRITE"], "revoke": []},
            # Creating subject needs WRITE on the policy's own policy:/ resource,
            # otherwise Ditto refuses to create it (would lock the creator out).
            "policy:/": {"grant": ["READ", "WRITE"], "revoke": []},
        },
    }


@pytest.fixture(autouse=True)
def cleanup():
    yield
    server.client.delete(f"/api/2/policies/{POLICY_ID}")


def test_put_policy_creates():
    result = server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})
    assert result["policyId"] == POLICY_ID


def test_put_policy_refuses_overwrite_by_default():
    server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})
    with pytest.raises(RuntimeError, match="already exists"):
        server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})


def test_get_policy():
    server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})
    policy = server.get_policy(POLICY_ID)
    assert policy["policyId"] == POLICY_ID
    assert "DEFAULT" in policy["entries"]


def test_policy_entries_get_and_set():
    server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})

    entries = server.get_policy_entries(POLICY_ID)
    assert "DEFAULT" in entries

    server.set_policy_entry(POLICY_ID, "DEVICES", _entry("nginx:other"))
    entry = server.get_policy_entries(POLICY_ID, label="DEVICES")
    assert entry["subjects"]["nginx:other"]["type"] == "generated"


def test_delete_policy_entry_requires_confirm():
    server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry(), "DEVICES": _entry("nginx:other")}})
    with pytest.raises(ValueError, match="confirm"):
        server.delete_policy_entry(POLICY_ID, "DEVICES")
    server.delete_policy_entry(POLICY_ID, "DEVICES", confirm=True)
    entries = server.get_policy_entries(POLICY_ID)
    assert "DEVICES" not in entries


def test_delete_policy_requires_confirm():
    server.put_policy(POLICY_ID, {"entries": {"DEFAULT": _entry()}})
    with pytest.raises(ValueError, match="confirm"):
        server.delete_policy(POLICY_ID)
    result = server.delete_policy(POLICY_ID, confirm=True)
    assert result["deleted"] is True
