import pytest

import awsiotcoremcpserver as server

THING_NAME = "pytest-thing"
THING_TYPE = "pytest-thing-type"
GROUP_NAME = "pytest-group"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    try:
        server.client.delete_thing(thingName=THING_NAME)
    except server.client.exceptions.ResourceNotFoundException:
        pass
    try:
        server.client.delete_thing_group(thingGroupName=GROUP_NAME)
    except server.client.exceptions.ResourceNotFoundException:
        pass


def test_create_and_get_thing():
    result = server.create_thing(THING_NAME, attributes={"location": "lab-1"})
    assert result["thingName"] == THING_NAME

    fetched = server.get_thing(THING_NAME)
    assert fetched["attributes"] == {"location": "lab-1"}


def test_create_thing_refuses_overwrite_by_default():
    server.create_thing(THING_NAME)
    with pytest.raises(RuntimeError, match="already exists"):
        server.create_thing(THING_NAME)


def test_create_thing_overwrite_true_updates():
    server.create_thing(THING_NAME, attributes={"location": "a"})
    server.create_thing(THING_NAME, attributes={"location": "b"}, overwrite=True)
    assert server.get_thing(THING_NAME)["attributes"]["location"] == "b"


def test_update_thing_merges_attributes_by_default():
    server.create_thing(THING_NAME, attributes={"a": "1"})
    server.update_thing(THING_NAME, attributes={"b": "2"})
    attrs = server.get_thing(THING_NAME)["attributes"]
    assert attrs == {"a": "1", "b": "2"}


def test_update_thing_replaces_attributes_when_merge_false():
    server.create_thing(THING_NAME, attributes={"a": "1"})
    server.update_thing(THING_NAME, attributes={"b": "2"}, attributes_merge=False)
    attrs = server.get_thing(THING_NAME)["attributes"]
    assert attrs == {"b": "2"}


def test_delete_thing_requires_confirm():
    server.create_thing(THING_NAME)
    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing(THING_NAME)
    result = server.delete_thing(THING_NAME, confirm=True)
    assert result["deleted"] is True
    with pytest.raises(RuntimeError):
        server.get_thing(THING_NAME)


def test_list_things_includes_created_thing():
    server.create_thing(THING_NAME)
    names = {t["thingName"] for t in server.list_things()["things"]}
    assert THING_NAME in names


def test_thing_type_lifecycle():
    server.create_thing_type(THING_TYPE, description="a test type")
    types_ = {t["thingTypeName"] for t in server.list_thing_types()["thingTypes"]}
    assert THING_TYPE in types_

    fetched = server.get_thing_type(THING_TYPE)
    assert fetched["thingTypeMetadata"]["deprecated"] is False

    result = server.deprecate_thing_type(THING_TYPE)
    assert result["deprecated"] is True
    assert server.get_thing_type(THING_TYPE)["thingTypeMetadata"]["deprecated"] is True

    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing_type(THING_TYPE)
    server.delete_thing_type(THING_TYPE, confirm=True)


def test_thing_group_lifecycle_and_membership():
    server.create_thing(THING_NAME)
    server.create_thing_group(GROUP_NAME, attributes={"env": "test"})

    group = server.get_thing_group(GROUP_NAME)
    assert group["thingGroupName"] == GROUP_NAME

    server.modify_thing_group_membership(THING_NAME, GROUP_NAME, action="add")
    members = server.list_things_in_thing_group(GROUP_NAME)["things"]
    assert THING_NAME in members

    server.modify_thing_group_membership(THING_NAME, GROUP_NAME, action="remove")
    members_after = server.list_things_in_thing_group(GROUP_NAME)["things"]
    assert THING_NAME not in members_after

    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing_group(GROUP_NAME)
    server.delete_thing_group(GROUP_NAME, confirm=True)
