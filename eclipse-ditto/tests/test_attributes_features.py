import pytest

import dittomcpserver as server

THING_ID = "org.eclipse.ditto:pytest-attr-feat"


@pytest.fixture(autouse=True)
def seed_thing():
    server.put_thing(THING_ID, {"attributes": {}}, overwrite=True)
    yield
    server.client.delete(f"/api/2/things/{THING_ID}")
    # Deleting a thing does not delete its auto-created implicit policy;
    # clean it up too so the next test's put_thing(overwrite=True) isn't
    # blocked by a leftover policy with the same ID.
    server.client.delete(f"/api/2/policies/{THING_ID}")


def test_attributes_whole_object_crud():
    # attributes is already a present-but-empty resource from seed_thing, so
    # this must be an overwrite, not a fresh create.
    result = server.set_thing_attributes(THING_ID, {"location": "lab-1", "owner": "qa"}, overwrite=True)
    assert result["path"] is None

    attrs = server.get_thing_attributes(THING_ID)
    assert attrs == {"location": "lab-1", "owner": "qa"}

    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing_attributes(THING_ID)
    server.delete_thing_attributes(THING_ID, confirm=True)
    assert server.get_thing_attributes(THING_ID) == {}


def test_attributes_single_path():
    server.set_thing_attributes(THING_ID, "lab-2", path="location")
    assert server.get_thing_attributes(THING_ID, path="location") == "lab-2"

    server.delete_thing_attributes(THING_ID, path="location", confirm=True)
    assert server.get_thing_attributes(THING_ID) == {}


def test_attributes_refuses_overwrite_by_default():
    server.set_thing_attributes(THING_ID, "lab-1", path="location")
    with pytest.raises(RuntimeError, match="already exists"):
        server.set_thing_attributes(THING_ID, "lab-2", path="location")
    server.set_thing_attributes(THING_ID, "lab-2", path="location", overwrite=True)
    assert server.get_thing_attributes(THING_ID, path="location") == "lab-2"


def test_feature_whole_crud():
    feature = {"properties": {"value": 21.5}}
    # Ditto's PUT feature response body is the feature itself (no thingId envelope).
    result = server.put_feature(THING_ID, "temperature", feature)
    assert result["properties"]["value"] == 21.5

    fetched = server.get_feature(THING_ID, "temperature")
    assert fetched["properties"]["value"] == 21.5

    with pytest.raises(ValueError, match="confirm"):
        server.delete_feature(THING_ID, "temperature")
    server.delete_feature(THING_ID, "temperature", confirm=True)
    assert server.get_feature(THING_ID, "temperature") == {}


def test_feature_properties_path_and_desired():
    server.put_feature(THING_ID, "temperature", {"properties": {"value": 20}})

    server.set_feature_properties(THING_ID, "temperature", 25, path="value", overwrite=True)
    assert server.get_feature_properties(THING_ID, "temperature", path="value") == 25

    server.set_feature_properties(THING_ID, "temperature", 30, path="value", desired=True)
    assert server.get_feature_properties(THING_ID, "temperature", path="value", desired=True) == 30
    # actual (non-desired) value must be unaffected by the desired write
    assert server.get_feature_properties(THING_ID, "temperature", path="value") == 25

    server.delete_feature_properties(THING_ID, "temperature", path="value", desired=True, confirm=True)
    assert server.get_feature_properties(THING_ID, "temperature", desired=True) == {}


def test_feature_definition_crud():
    server.put_feature(THING_ID, "temperature", {"properties": {"value": 20}})
    assert server.get_feature_definition(THING_ID, "temperature") == {}

    result = server.set_feature_definition(THING_ID, "temperature", ["com.acme:sensor:1.0.0"])
    assert result["definition"] == ["com.acme:sensor:1.0.0"]
    assert server.get_feature_definition(THING_ID, "temperature") == ["com.acme:sensor:1.0.0"]

    server.delete_feature_definition(THING_ID, "temperature", confirm=True)
    assert server.get_feature_definition(THING_ID, "temperature") == {}
