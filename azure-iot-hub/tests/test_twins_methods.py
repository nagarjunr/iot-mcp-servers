import httpx
import pytest
import respx

import azureiothubmcpserver as server

BASE = "https://test-hub.azure-devices-mock.net"
DEVICE = "pytest-device"
MODULE = "pytest-module"


@respx.mock
def test_get_device_twin():
    respx.get(f"{BASE}/twins/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "properties": {"desired": {}, "reported": {}}})
    )
    result = server.get_device_twin(DEVICE)
    assert result["deviceId"] == DEVICE


@respx.mock
def test_update_device_twin_requires_tags_or_desired():
    with pytest.raises(ValueError, match="tags or desired_properties"):
        server.update_device_twin(DEVICE)


@respx.mock
def test_update_device_twin_sends_merge_patch_body():
    route = respx.patch(f"{BASE}/twins/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "properties": {"desired": {"on": True}}})
    )
    result = server.update_device_twin(DEVICE, desired_properties={"on": True})
    assert result["properties"]["desired"]["on"] is True
    assert b'"desired"' in route.calls.last.request.content
    assert b'"tags"' not in route.calls.last.request.content


@respx.mock
def test_update_device_twin_sends_if_match_when_etag_given():
    route = respx.patch(f"{BASE}/twins/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE})
    )
    server.update_device_twin(DEVICE, tags={"env": "test"}, etag="abc123")
    assert route.calls.last.request.headers["If-Match"] == '"abc123"'


@respx.mock
def test_replace_device_twin():
    respx.put(f"{BASE}/twins/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "tags": {"a": 1}})
    )
    result = server.replace_device_twin(DEVICE, tags={"a": 1})
    assert result["tags"]["a"] == 1


@respx.mock
def test_get_module_twin():
    respx.get(f"{BASE}/twins/{DEVICE}/modules/{MODULE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "moduleId": MODULE})
    )
    result = server.get_module_twin(DEVICE, MODULE)
    assert result["moduleId"] == MODULE


@respx.mock
def test_invoke_device_method():
    route = respx.post(f"{BASE}/twins/{DEVICE}/methods").mock(
        return_value=httpx.Response(200, json={"status": 200, "payload": {"result": "ok"}})
    )
    result = server.invoke_device_method(DEVICE, "reboot", payload={"delay": 5})
    assert result["status"] == 200
    assert b'"reboot"' in route.calls.last.request.content


@respx.mock
def test_invoke_module_method():
    respx.post(f"{BASE}/twins/{DEVICE}/modules/{MODULE}/methods").mock(
        return_value=httpx.Response(200, json={"status": 200, "payload": {}})
    )
    result = server.invoke_module_method(DEVICE, MODULE, "restart")
    assert result["status"] == 200


@respx.mock
def test_invoke_device_method_failure_raises():
    respx.post(f"{BASE}/twins/{DEVICE}/methods").mock(
        return_value=httpx.Response(404, json={"Message": "device not found"})
    )
    with pytest.raises(RuntimeError, match="404"):
        server.invoke_device_method(DEVICE, "reboot")
