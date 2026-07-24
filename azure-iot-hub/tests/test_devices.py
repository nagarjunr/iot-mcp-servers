import httpx
import pytest
import respx

import azureiothubmcpserver as server

BASE = "https://test-hub.azure-devices-mock.net"
DEVICE = "pytest-device"


@respx.mock
def test_get_device():
    respx.get(f"{BASE}/devices/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "status": "enabled", "etag": "abc"})
    )
    result = server.get_device(DEVICE)
    assert result["deviceId"] == DEVICE
    assert result["status"] == "enabled"


@respx.mock
def test_get_device_sends_sas_auth_header():
    route = respx.get(f"{BASE}/devices/{DEVICE}").mock(return_value=httpx.Response(200, json={"deviceId": DEVICE}))
    server.get_device(DEVICE)
    sent_request = route.calls.last.request
    assert sent_request.headers["Authorization"].startswith("SharedAccessSignature ")
    assert "sr=test-hub.azure-devices-mock.net" in sent_request.headers["Authorization"]


@respx.mock
def test_create_device_refuses_overwrite_by_default():
    respx.get(f"{BASE}/devices/{DEVICE}").mock(return_value=httpx.Response(200, json={"deviceId": DEVICE}))
    with pytest.raises(RuntimeError, match="already exists"):
        server.create_device(DEVICE)


@respx.mock
def test_create_device_creates_when_absent():
    respx.get(f"{BASE}/devices/{DEVICE}").mock(return_value=httpx.Response(404, json={"Message": "not found"}))
    put_route = respx.put(f"{BASE}/devices/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "status": "enabled"})
    )
    result = server.create_device(DEVICE)
    assert result["deviceId"] == DEVICE
    sent_body = put_route.calls.last.request.content
    assert b'"deviceId":"pytest-device"' in sent_body or b"pytest-device" in sent_body


@respx.mock
def test_create_device_overwrite_true_skips_existence_check():
    put_route = respx.put(f"{BASE}/devices/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE})
    )
    server.create_device(DEVICE, overwrite=True)
    assert put_route.called
    # No GET should have been issued when overwrite=True.
    assert not respx.get(f"{BASE}/devices/{DEVICE}").called


@respx.mock
def test_update_device_fetches_then_puts_merged_status():
    respx.get(f"{BASE}/devices/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "status": "enabled"})
    )
    put_route = respx.put(f"{BASE}/devices/{DEVICE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "status": "disabled"})
    )
    result = server.update_device(DEVICE, status="disabled")
    assert result["status"] == "disabled"
    assert b'"disabled"' in put_route.calls.last.request.content


@respx.mock
def test_delete_device_requires_confirm():
    with pytest.raises(ValueError, match="confirm"):
        server.delete_device(DEVICE)


@respx.mock
def test_delete_device_sends_wildcard_if_match_by_default():
    route = respx.delete(f"{BASE}/devices/{DEVICE}").mock(return_value=httpx.Response(204))
    result = server.delete_device(DEVICE, confirm=True)
    assert result["deleted"] is True
    assert route.calls.last.request.headers["If-Match"] == "*"


@respx.mock
def test_list_devices():
    respx.get(f"{BASE}/devices").mock(
        return_value=httpx.Response(200, json=[{"deviceId": "a"}, {"deviceId": "b"}])
    )
    result = server.list_devices()
    assert result["count"] == 2


@respx.mock
def test_query_devices_returns_continuation_token():
    respx.post(f"{BASE}/devices/query").mock(
        return_value=httpx.Response(
            200, json=[{"deviceId": DEVICE}], headers={"x-ms-continuation": "next-token"}
        )
    )
    result = server.query_devices("SELECT * FROM devices")
    assert result["count"] == 1
    assert result["continuation_token"] == "next-token"
