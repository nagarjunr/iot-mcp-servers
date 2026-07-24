import httpx
import pytest
import respx

import azureiothubmcpserver as server

BASE = "https://test-hub.azure-devices-mock.net"


@respx.mock
def test_create_scheduled_job_twin_update():
    route = respx.put(f"{BASE}/jobs/v2/job-1").mock(
        return_value=httpx.Response(200, json={"jobId": "job-1", "type": "scheduleUpdateTwin", "status": "queued"})
    )
    result = server.create_scheduled_job(
        "job-1", "scheduleUpdateTwin", "deviceId IN ['a','b']", twin_patch={"tags": {"env": "test"}}
    )
    assert result["jobId"] == "job-1"
    assert b'"scheduleUpdateTwin"' in route.calls.last.request.content


@respx.mock
def test_create_scheduled_job_method_requires_method_name():
    with pytest.raises(ValueError, match="method_name"):
        server.create_scheduled_job("job-2", "scheduleDeviceMethod", "deviceId IN ['a']")


@respx.mock
def test_create_scheduled_job_device_method():
    route = respx.put(f"{BASE}/jobs/v2/job-3").mock(
        return_value=httpx.Response(200, json={"jobId": "job-3", "type": "scheduleDeviceMethod"})
    )
    server.create_scheduled_job(
        "job-3", "scheduleDeviceMethod", "deviceId IN ['a']", method_name="reboot", method_payload={"delay": 1}
    )
    assert b'"reboot"' in route.calls.last.request.content


@respx.mock
def test_get_scheduled_job():
    respx.get(f"{BASE}/jobs/v2/job-1").mock(
        return_value=httpx.Response(200, json={"jobId": "job-1", "status": "completed"})
    )
    result = server.get_scheduled_job("job-1")
    assert result["status"] == "completed"


@respx.mock
def test_query_scheduled_jobs():
    respx.get(f"{BASE}/jobs/v2/query").mock(
        return_value=httpx.Response(200, json=[{"jobId": "job-1"}, {"jobId": "job-2"}])
    )
    result = server.query_scheduled_jobs(job_status="completed")
    assert result["count"] == 2


@respx.mock
def test_cancel_scheduled_job_requires_confirm():
    with pytest.raises(ValueError, match="confirm"):
        server.cancel_scheduled_job("job-1")


@respx.mock
def test_cancel_scheduled_job():
    respx.post(f"{BASE}/jobs/v2/job-1/cancel").mock(
        return_value=httpx.Response(200, json={"jobId": "job-1", "status": "cancelled"})
    )
    result = server.cancel_scheduled_job("job-1", confirm=True)
    assert result["status"] == "cancelled"


@respx.mock
def test_get_device_statistics():
    respx.get(f"{BASE}/statistics/devices").mock(
        return_value=httpx.Response(200, json={"totalDeviceCount": 10, "enabledDeviceCount": 8, "disabledDeviceCount": 2})
    )
    result = server.get_device_statistics()
    assert result["totalDeviceCount"] == 10


@respx.mock
def test_get_service_statistics():
    respx.get(f"{BASE}/statistics/service").mock(return_value=httpx.Response(200, json={"connectedDeviceCount": 5}))
    result = server.get_service_statistics()
    assert result["connectedDeviceCount"] == 5


@respx.mock
def test_purge_c2d_message_queue():
    respx.delete(f"{BASE}/devices/pytest-device/commands").mock(return_value=httpx.Response(200, json={}))
    result = server.purge_c2d_message_queue("pytest-device")
    assert result["purged"] is True
