import pytest

import dittomcpserver as server

THING_ID = "org.eclipse.ditto:pytest-messages"


@pytest.fixture(autouse=True)
def seed_thing():
    server.put_thing(
        THING_ID,
        {"attributes": {}, "features": {"coffee-brewer": {"properties": {"brewed-coffees": 0}}}},
        overwrite=True,
    )
    yield
    server.client.delete(f"/api/2/things/{THING_ID}")
    server.client.delete(f"/api/2/policies/{THING_ID}")


def test_send_message_fire_and_forget():
    # timeout=0 -> fire-and-forget, no device needs to be listening for a response.
    result = server.send_message(THING_ID, "makeCoffee", {"cups": 1}, timeout=0)
    assert result["status"] == 202


def test_send_message_scoped_to_feature():
    result = server.send_message(THING_ID, "brew", {"strength": "strong"}, feature_id="coffee-brewer", timeout=0)
    assert result["status"] == 202


def test_send_message_outbox_direction():
    result = server.send_message(THING_ID, "coffeeReady", {"cups": 1}, direction="outbox", timeout=0)
    assert result["status"] == 202


def test_claim_thing_fire_and_forget():
    result = server.claim_thing(THING_ID, {"claimant": "pytest"}, timeout=0)
    assert result["status"] == 202
