import threading
import time

import dittomcpserver as server

THING_ID = "org.eclipse.ditto:pytest-events"


def test_poll_thing_changes_captures_an_update():
    server.put_thing(THING_ID, {"attributes": {}}, overwrite=True)

    def make_change_after_delay() -> None:
        time.sleep(3.0)
        server.set_thing_attributes(THING_ID, "changed", path="marker", overwrite=True)

    threading.Thread(target=make_change_after_delay, daemon=True).start()

    result = server.poll_thing_changes(thing_ids=[THING_ID], duration_seconds=10.0, max_events=5)

    assert result["count"] >= 1
    assert any(e.get("thingId") == THING_ID for e in result["events"] if isinstance(e, dict))

    server.client.delete(f"/api/2/things/{THING_ID}")


def test_poll_thing_changes_times_out_with_no_events():
    result = server.poll_thing_changes(thing_ids=["org.eclipse.ditto:no-such-thing-ever"], duration_seconds=2.0)
    assert result["count"] == 0
    assert result["stopped_reason"] == "timeout"
