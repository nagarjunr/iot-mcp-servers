import pytest

import dittomcpserver as server


def test_get_logging_config_all():
    result = server.get_logging_config()
    assert isinstance(result, (dict, list))


def test_set_and_get_logging_config_for_module():
    server.set_logging_config(level="INFO", logger="org.eclipse.ditto", module_name="gateway")
    result = server.get_logging_config(module_name="gateway")
    assert result is not None


def test_get_devops_config_with_path():
    result = server.get_devops_config(path="ditto.gateway.authentication.devops.secured")
    assert isinstance(result, dict)


def test_send_devops_piggyback_scoped_to_service():
    # Broadcasting through /system/distributedPubSubMediator (no service_name)
    # times out (408) on this single-node test stack -- there's no cluster to
    # aggregate a response from. Scoping to a specific service_name sends the
    # command directly instead, which works even single-node.
    result = server.send_devops_piggyback(
        command={
            "targetActorSelection": "/user/thingsRoot/persistenceCleanup",
            "headers": {},
            "piggybackCommand": {"type": "status.commands:retrieveHealth"},
        },
        service_name="things",
    )
    assert isinstance(result, dict)


def test_send_devops_piggyback_instance_index_requires_service_name():
    with pytest.raises(ValueError, match="service_name"):
        server.send_devops_piggyback(command={}, instance_index="0")
