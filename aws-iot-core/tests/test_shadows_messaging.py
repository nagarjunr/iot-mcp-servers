import pytest

import awsiotcoremcpserver as server

THING_NAME = "pytest-shadow-thing"


@pytest.fixture(autouse=True)
def seed_thing():
    server.create_thing(THING_NAME, overwrite=True)
    yield
    server.client.delete_thing(thingName=THING_NAME)


def test_classic_shadow_lifecycle():
    assert server.get_thing_shadow(THING_NAME) == {}

    result = server.update_thing_shadow(THING_NAME, desired={"on": True}, reported={"on": False})
    assert result["state"]["desired"] == {"on": True}
    assert result["state"]["reported"] == {"on": False}

    fetched = server.get_thing_shadow(THING_NAME)
    assert fetched["state"]["desired"] == {"on": True}
    assert fetched["state"]["delta"] == {"on": True}

    with pytest.raises(ValueError, match="confirm"):
        server.delete_thing_shadow(THING_NAME)
    server.delete_thing_shadow(THING_NAME, confirm=True)
    assert server.get_thing_shadow(THING_NAME) == {}


def test_update_thing_shadow_requires_desired_or_reported():
    with pytest.raises(ValueError, match="desired or reported"):
        server.update_thing_shadow(THING_NAME)


def test_named_shadow_lifecycle():
    server.update_thing_shadow(THING_NAME, reported={"battery": 80}, shadow_name="power")
    names = server.list_named_shadows_for_thing(THING_NAME)["shadowNames"]
    assert "power" in names

    fetched = server.get_thing_shadow(THING_NAME, shadow_name="power")
    assert fetched["state"]["reported"]["battery"] == 80

    server.delete_thing_shadow(THING_NAME, shadow_name="power", confirm=True)


def test_publish_message():
    result = server.publish_message("pytest/topic", "hello", qos=0)
    assert result["published"] is True
    assert result["topic"] == "pytest/topic"
