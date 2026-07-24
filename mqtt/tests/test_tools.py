import time
import uuid

import pytest

import mqttmcpserver as server


def _unique_topic(prefix: str) -> str:
    return f"pytest/{prefix}-{uuid.uuid4().hex[:8]}"


def test_get_connection_status():
    status = server.get_connection_status()
    assert status["connected"] is True
    assert status["host"] == "localhost"
    assert status["protocol"] == "MQTTv5"


def test_publish_qos0_fire_and_forget():
    topic = _unique_topic("qos0")
    result = server.publish_message(topic, "hello", qos=0)
    assert result["qos"] == 0
    assert result["acknowledged"] is True


def test_publish_qos1_waits_for_ack():
    topic = _unique_topic("qos1")
    result = server.publish_message(topic, "hello", qos=1)
    assert result["acknowledged"] is True
    assert result["mid"] is not None


def test_start_and_stop_subscription():
    topic = _unique_topic("basic")
    sub = server.start_subscription(topic)
    assert sub["topic_filter"] == topic

    server.publish_message(topic, "payload-1", qos=1)
    time.sleep(0.3)

    result = server.get_messages(sub["session_id"], timeout_seconds=2.0)
    assert result["count"] == 1
    assert result["messages"][0]["payload"] == "payload-1"
    assert result["messages"][0]["topic"] == topic

    stopped = server.stop_subscription(sub["session_id"])
    assert stopped["stopped"] is True


def test_subscription_wildcard_matches_multiple_topics():
    prefix = _unique_topic("wild")
    sub = server.start_subscription(f"{prefix}/#")

    server.publish_message(f"{prefix}/a", "1", qos=1)
    server.publish_message(f"{prefix}/b/c", "2", qos=1)
    time.sleep(0.3)

    result = server.get_messages(sub["session_id"], timeout_seconds=2.0, max_messages=10)
    topics = {m["topic"] for m in result["messages"]}
    assert topics == {f"{prefix}/a", f"{prefix}/b/c"}

    server.stop_subscription(sub["session_id"])


def test_get_messages_returns_empty_without_blocking_when_timeout_zero():
    topic = _unique_topic("empty")
    sub = server.start_subscription(topic)
    result = server.get_messages(sub["session_id"], timeout_seconds=0.0)
    assert result == {"messages": [], "count": 0, "buffered_remaining": 0}
    server.stop_subscription(sub["session_id"])


def test_get_messages_unknown_session_raises():
    with pytest.raises(ValueError, match="No such subscription session"):
        server.get_messages("does-not-exist")


def test_stop_subscription_unknown_session_raises():
    with pytest.raises(ValueError, match="No such subscription session"):
        server.stop_subscription("does-not-exist")


def test_list_subscriptions_reflects_active_sessions():
    topic = _unique_topic("list")
    before = len(server.list_subscriptions()["sessions"])
    sub = server.start_subscription(topic)
    during = server.list_subscriptions()["sessions"]
    assert len(during) == before + 1
    assert any(s["session_id"] == sub["session_id"] for s in during)
    server.stop_subscription(sub["session_id"])
    after = len(server.list_subscriptions()["sessions"])
    assert after == before


def test_two_sessions_on_same_filter_both_receive_and_refcount_correctly():
    topic = _unique_topic("shared")
    sub_a = server.start_subscription(topic)
    sub_b = server.start_subscription(topic)

    server.publish_message(topic, "broadcast", qos=1)
    time.sleep(0.3)

    result_a = server.get_messages(sub_a["session_id"], timeout_seconds=2.0)
    result_b = server.get_messages(sub_b["session_id"], timeout_seconds=2.0)
    assert result_a["count"] == 1
    assert result_b["count"] == 1

    server.stop_subscription(sub_a["session_id"])
    # sub_b still active on the same filter -- broker subscription should remain.
    server.publish_message(topic, "still-listening", qos=1)
    time.sleep(0.3)
    result_b2 = server.get_messages(sub_b["session_id"], timeout_seconds=2.0)
    assert result_b2["count"] == 1

    server.stop_subscription(sub_b["session_id"])


def test_publish_with_mqtt5_properties_round_trip():
    topic = _unique_topic("props")
    sub = server.start_subscription(topic)

    server.publish_message(
        topic,
        "with-props",
        qos=1,
        content_type="text/plain",
        user_properties={"source": "pytest", "priority": "high"},
        response_topic=f"{topic}/reply",
        correlation_data="corr-abc",
    )
    time.sleep(0.3)

    result = server.get_messages(sub["session_id"], timeout_seconds=2.0)
    msg = result["messages"][0]
    assert msg["content_type"] == "text/plain"
    assert msg["user_properties"] == {"source": "pytest", "priority": "high"}
    assert msg["response_topic"] == f"{topic}/reply"

    server.stop_subscription(sub["session_id"])


def test_discover_topics_finds_retained_messages():
    prefix = _unique_topic("discover")
    server.publish_message(f"{prefix}/x", "retained-x", qos=1, retain=True)
    server.publish_message(f"{prefix}/y", "retained-y", qos=1, retain=True)

    result = server.discover_topics(f"{prefix}/#", duration_seconds=3.0)
    topics = {t["topic"] for t in result["topics"]}
    assert topics == {f"{prefix}/x", f"{prefix}/y"}

    # Clean up retained messages so they don't leak into other test runs.
    server.publish_message(f"{prefix}/x", "", qos=1, retain=True)
    server.publish_message(f"{prefix}/y", "", qos=1, retain=True)


def test_discover_topics_times_out_with_no_matches():
    prefix = _unique_topic("nomatch")
    result = server.discover_topics(f"{prefix}/#", duration_seconds=1.5)
    assert result == {"topics": [], "count": 0, "stopped_reason": "timeout"}
