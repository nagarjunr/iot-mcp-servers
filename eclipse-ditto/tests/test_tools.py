import time

import pytest

import dittomcpserver as server

THING_ID = "org.eclipse.ditto:pytest-thing"


@pytest.fixture(scope="module", autouse=True)
def seed_thing():
    resp = server.client.put(
        f"/api/2/things/{THING_ID}",
        json={
            "attributes": {"location": "pytest-lab"},
            "features": {"temperature": {"properties": {"value": 21.5}}},
        },
    )
    resp.raise_for_status()
    # Ditto's search index updates asynchronously after a write.
    time.sleep(3)
    yield


def test_get_thing():
    result = server.get_thing(THING_ID)
    assert result["thingId"] == THING_ID
    assert result["attributes"]["location"] == "pytest-lab"


def test_get_thing_features():
    result = server.get_thing_features(THING_ID)
    assert result["temperature"]["properties"]["value"] == 21.5


def test_get_thing_features_missing_thing_returns_empty():
    result = server.get_thing_features("org.eclipse.ditto:does-not-exist")
    assert result == {}


def test_get_thing_missing_raises():
    with pytest.raises(RuntimeError):
        server.get_thing("org.eclipse.ditto:does-not-exist")


def test_list_things_by_filter():
    result = server.list_things(
        namespaces=["org.eclipse.ditto"],
        filter='eq(attributes/location,"pytest-lab")',
    )
    ids = [item["thingId"] for item in result["items"]]
    assert THING_ID in ids
    assert result["count"] == len(result["items"])


def test_list_things_respects_limit():
    result = server.list_things(namespaces=["org.eclipse.ditto"], limit=1)
    assert len(result["items"]) <= 1
