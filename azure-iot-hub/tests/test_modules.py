import httpx
import pytest
import respx

import azureiothubmcpserver as server

BASE = "https://test-hub.azure-devices-mock.net"
DEVICE = "pytest-device"
MODULE = "pytest-module"


@respx.mock
def test_list_modules():
    respx.get(f"{BASE}/devices/{DEVICE}/modules").mock(
        return_value=httpx.Response(200, json=[{"moduleId": MODULE}])
    )
    result = server.list_modules(DEVICE)
    assert result["count"] == 1


@respx.mock
def test_get_module():
    respx.get(f"{BASE}/devices/{DEVICE}/modules/{MODULE}").mock(
        return_value=httpx.Response(200, json={"deviceId": DEVICE, "moduleId": MODULE})
    )
    result = server.get_module(DEVICE, MODULE)
    assert result["moduleId"] == MODULE


@respx.mock
def test_create_module_refuses_overwrite_by_default():
    respx.put(f"{BASE}/devices/{DEVICE}/modules/{MODULE}").mock(
        return_value=httpx.Response(412, json={"Message": "precondition"})
    )
    with pytest.raises(RuntimeError, match="already exists"):
        server.create_module(DEVICE, MODULE)


@respx.mock
def test_create_module_creates_when_absent():
    respx.put(f"{BASE}/devices/{DEVICE}/modules/{MODULE}").mock(
        return_value=httpx.Response(201, json={"deviceId": DEVICE, "moduleId": MODULE})
    )
    result = server.create_module(DEVICE, MODULE)
    assert result["moduleId"] == MODULE


@respx.mock
def test_delete_module_requires_confirm():
    with pytest.raises(ValueError, match="confirm"):
        server.delete_module(DEVICE, MODULE)


@respx.mock
def test_delete_module():
    respx.delete(f"{BASE}/devices/{DEVICE}/modules/{MODULE}").mock(return_value=httpx.Response(204))
    result = server.delete_module(DEVICE, MODULE, confirm=True)
    assert result["deleted"] is True
