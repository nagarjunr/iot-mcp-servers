import uuid

import pytest

import awsiotcoremcpserver as server


def test_topic_rule_lifecycle():
    rule_name = f"pytest_rule_{uuid.uuid4().hex[:8]}"
    sql = "SELECT * FROM 'pytest/topic'"
    actions = [{"republish": {"topic": "pytest/republished", "roleArn": "arn:aws:iam::123456789012:role/pytest-role"}}]

    result = server.put_topic_rule(rule_name, sql, actions)
    assert result["ruleName"] == rule_name

    fetched = server.get_topic_rule(rule_name)
    assert fetched["rule"]["sql"] == sql

    names = {r["ruleName"] for r in server.list_topic_rules()["rules"]}
    assert rule_name in names

    server.set_topic_rule_enabled(rule_name, enabled=False)
    assert server.get_topic_rule(rule_name)["rule"]["ruleDisabled"] is True

    new_sql = "SELECT * FROM 'pytest/topic/v2'"
    server.put_topic_rule(rule_name, new_sql, actions, overwrite=True)
    assert server.get_topic_rule(rule_name)["rule"]["sql"] == new_sql

    with pytest.raises(ValueError, match="confirm"):
        server.delete_topic_rule(rule_name)
    server.delete_topic_rule(rule_name, confirm=True)


def test_put_topic_rule_refuses_overwrite_by_default():
    rule_name = f"pytest_rule_{uuid.uuid4().hex[:8]}"
    sql = "SELECT * FROM 'pytest/topic'"
    actions = [{"republish": {"topic": "pytest/republished", "roleArn": "arn:aws:iam::123456789012:role/pytest-role"}}]
    server.put_topic_rule(rule_name, sql, actions)
    with pytest.raises(RuntimeError):
        server.put_topic_rule(rule_name, sql, actions)
    server.delete_topic_rule(rule_name, confirm=True)


def test_get_endpoint():
    result = server.get_endpoint()
    assert "endpointAddress" in result
