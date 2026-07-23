import time

import pytest

import dittomcpserver as server

THING_A = "org.eclipse.ditto:pytest-crud-a"
THING_B = "org.eclipse.ditto:pytest-crud-b"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    for thing_id in (THING_A, THING_B):
        server.client.delete(f"/api/2/things/{thing_id}")
        # Deleting a thing does not delete its (often same-ID, auto-created)
        # policy; clean it up too so the next test's create isn't blocked by
        # a leftover policy with the same ID.
        server.client.delete(f"/api/2/policies/{thing_id}")


def test_put_thing_creates():
    result = server.put_thing(THING_A, {"attributes": {"name": "a"}})
    assert result["thingId"] == THING_A
    assert result["attributes"]["name"] == "a"


def test_put_thing_refuses_overwrite_by_default():
    server.put_thing(THING_A, {"attributes": {"name": "a"}})
    with pytest.raises(RuntimeError, match="already exists"):
        server.put_thing(THING_A, {"attributes": {"name": "b"}})


def test_put_thing_overwrite_true_replaces():
    server.put_thing(THING_A, {"attributes": {"name": "a"}})
    # Updating an existing thing returns 204 No Content, so check via get_thing.
    server.put_thing(THING_A, {"attributes": {"name": "b"}}, overwrite=True)
    assert server.get_thing(THING_A)["attributes"]["name"] == "b"


def test_patch_thing_merges():
    server.put_thing(THING_A, {"attributes": {"name": "a", "keep": "me"}})
    server.patch_thing(THING_A, {"attributes": {"name": "patched"}})
    attrs = server.get_thing(THING_A)["attributes"]
    assert attrs["name"] == "patched"
    assert attrs["keep"] == "me"


def test_delete_thing_requires_confirm():
    server.put_thing(THING_A, {"attributes": {}})
    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing(THING_A)


def test_delete_thing_with_confirm():
    server.put_thing(THING_A, {"attributes": {}})
    result = server.delete_thing(THING_A, confirm=True)
    assert result["deleted"] is True
    with pytest.raises(RuntimeError):
        server.get_thing(THING_A)


def test_get_things_bulk():
    server.put_thing(THING_A, {"attributes": {"name": "a"}})
    server.put_thing(THING_B, {"attributes": {"name": "b"}})
    results = server.get_things([THING_A, THING_B])
    ids = {t["thingId"] for t in results}
    assert ids == {THING_A, THING_B}


def test_thing_policy_id_get_set():
    server.put_thing(THING_A, {"attributes": {}})
    policy_id = server.get_thing_policy_id(THING_A)
    assert policy_id == THING_A  # Ditto defaults the policy ID to the thing ID on creation

    server.put_policy(THING_B, {"entries": {"DEFAULT": _default_policy_entry()}})
    result = server.set_thing_policy_id(THING_A, THING_B)
    assert result["policyId"] == THING_B
    assert server.get_thing_policy_id(THING_A) == THING_B

    # THING_A now depends on policy THING_B for access -- delete THING_A
    # first, while that policy is still valid, otherwise THING_A becomes
    # permanently inaccessible (its policy would be gone) and the cleanup
    # fixture's delete would silently fail, poisoning later tests.
    server.client.delete(f"/api/2/things/{THING_A}")
    server.delete_policy(THING_B, confirm=True)


def test_thing_definition_crud():
    server.put_thing(THING_A, {"attributes": {}})
    assert server.get_thing_definition(THING_A) == {}

    result = server.set_thing_definition(THING_A, "com.acme:widget:1.0.0")
    assert result["definition"] == "com.acme:widget:1.0.0"
    assert server.get_thing_definition(THING_A) == "com.acme:widget:1.0.0"

    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing_definition(THING_A)
    server.delete_thing_definition(THING_A, confirm=True)
    assert server.get_thing_definition(THING_A) == {}


def test_count_things():
    server.put_thing(THING_A, {"attributes": {"marker": "count-test"}})
    time.sleep(3)  # search index eventual consistency
    count = server.count_things(namespaces=["org.eclipse.ditto"], filter='eq(attributes/marker,"count-test")')
    assert count >= 1


def test_whoami():
    result = server.whoami()
    assert "subjects" in result


def _default_policy_entry() -> dict:
    return {
        "subjects": {"nginx:ditto": {"type": "generated"}},
        "resources": {
            "thing:/": {"grant": ["READ", "WRITE"], "revoke": []},
            "policy:/": {"grant": ["READ", "WRITE"], "revoke": []},
            "message:/": {"grant": ["READ", "WRITE"], "revoke": []},
        },
    }
