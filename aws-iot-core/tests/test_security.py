import uuid

import pytest

import awsiotcoremcpserver as server

THING_NAME = "pytest-security-thing"


@pytest.fixture(autouse=True)
def seed_thing():
    server.create_thing(THING_NAME, overwrite=True)
    yield
    try:
        server.client.delete_thing(thingName=THING_NAME)
    except server.client.exceptions.ResourceNotFoundException:
        pass


def test_create_keys_and_certificate_returns_private_key():
    result = server.create_keys_and_certificate()
    assert result["certificateArn"]
    assert "PRIVATE KEY" in result["keyPair"]["PrivateKey"]

    server.set_certificate_status(result["certificateId"], "INACTIVE")
    server.delete_certificate(result["certificateId"], confirm=True)


def test_certificate_status_lifecycle():
    created = server.create_keys_and_certificate()
    cert_id = created["certificateId"]

    fetched = server.get_certificate(cert_id)
    assert fetched["certificateDescription"]["status"] == "ACTIVE"

    server.set_certificate_status(cert_id, "INACTIVE")
    assert server.get_certificate(cert_id)["certificateDescription"]["status"] == "INACTIVE"

    with pytest.raises(ValueError, match="confirm"):
        server.delete_certificate(cert_id)
    server.delete_certificate(cert_id, confirm=True)


def test_list_certificates_includes_created():
    created = server.create_keys_and_certificate()
    ids = {c["certificateId"] for c in server.list_certificates()["certificates"]}
    assert created["certificateId"] in ids
    server.set_certificate_status(created["certificateId"], "INACTIVE")
    server.delete_certificate(created["certificateId"], confirm=True)


def test_policy_lifecycle():
    policy_name = f"pytest-policy-{uuid.uuid4().hex[:8]}"
    doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "iot:Connect", "Resource": "*"}]}

    server.create_policy(policy_name, doc)
    fetched = server.get_policy(policy_name)
    assert fetched["policyName"] == policy_name

    with pytest.raises(RuntimeError, match="already exists"):
        server.create_policy(policy_name, doc)

    updated_doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "iot:Publish", "Resource": "*"}]}
    server.create_policy(policy_name, updated_doc, overwrite=True)

    names = {p["policyName"] for p in server.list_policies()["policies"]}
    assert policy_name in names

    with pytest.raises(ValueError, match="confirm"):
        server.delete_policy(policy_name)
    server.delete_policy(policy_name, confirm=True)


def test_policy_and_thing_principal_attachment():
    policy_name = f"pytest-policy-{uuid.uuid4().hex[:8]}"
    doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "iot:Connect", "Resource": "*"}]}
    server.create_policy(policy_name, doc)
    cert = server.create_keys_and_certificate()
    cert_arn = cert["certificateArn"]

    server.modify_policy_attachment(policy_name, cert_arn, action="attach")
    server.modify_thing_principal(THING_NAME, cert_arn, action="attach")

    principals = server.list_thing_principals(THING_NAME)["principals"]
    assert cert_arn in principals
    things = server.list_principal_things(cert_arn)["things"]
    assert THING_NAME in things

    server.modify_thing_principal(THING_NAME, cert_arn, action="detach")
    server.modify_policy_attachment(policy_name, cert_arn, action="detach")
    server.delete_policy(policy_name, confirm=True)
    server.set_certificate_status(cert["certificateId"], "INACTIVE")
    server.delete_certificate(cert["certificateId"], confirm=True)
