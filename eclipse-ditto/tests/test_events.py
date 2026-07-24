import threading
import time

import dittomcpserver as server

THING_ID = "org.eclipse.ditto:pytest-events"


def test_poll_thing_changes_captures_an_update():
    # Ditto's cluster-wide pub-sub subscription registration syncs on its own
    # periodic interval (observed ~60s in this lightweight single-node test
    # stack). A subscription started just before a change is published can
    # occasionally miss it if that sync hasn't landed yet -- eventual
    # consistency, not a bug in poll_thing_changes. Retry a few times so a
    # rare sync-lag miss doesn't fail the suite; a real regression would fail
    # every attempt.
    server.put_thing(THING_ID, {"attributes": {}}, overwrite=True)

    last_result = None
    for _attempt in range(3):

        def make_change_after_delay() -> None:
            time.sleep(3.0)
            server.set_thing_attributes(THING_ID, "changed", path="marker", overwrite=True)

        threading.Thread(target=make_change_after_delay, daemon=True).start()

        last_result = server.poll_thing_changes(thing_ids=[THING_ID], duration_seconds=10.0, max_events=5)
        if last_result["count"] >= 1:
            break

    assert last_result is not None
    assert last_result["count"] >= 1
    assert any(e.get("thingId") == THING_ID for e in last_result["events"] if isinstance(e, dict))

    server.client.delete(f"/api/2/things/{THING_ID}")


def test_poll_thing_changes_times_out_with_no_events():
    result = server.poll_thing_changes(thing_ids=["org.eclipse.ditto:no-such-thing-ever"], duration_seconds=2.0)
    assert result["count"] == 0
    assert result["stopped_reason"] == "timeout"
