import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
from typing import Annotated, Any, Literal

import httpx
import proton
import proton.utils
from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

API_VERSION = "2021-04-12"

_CONN_STR = os.environ["AZURE_IOT_HUB_CONNECTION_STRING"]


def _parse_connection_string(conn_str: str) -> dict[str, str]:
    parts = dict(p.split("=", 1) for p in conn_str.strip().rstrip(";").split(";"))
    missing = {"HostName", "SharedAccessKeyName", "SharedAccessKey"} - parts.keys()
    if missing:
        raise ValueError(f"AZURE_IOT_HUB_CONNECTION_STRING is missing required field(s): {', '.join(sorted(missing))}")
    return parts


_conn = _parse_connection_string(_CONN_STR)
HOSTNAME = _conn["HostName"]
_KEY_NAME = _conn["SharedAccessKeyName"]
_KEY = _conn["SharedAccessKey"]


def _generate_sas_token(resource_uri: str, key_name: str, key: str, ttl_seconds: int = 3600) -> str:
    """Generate an Azure IoT Hub SAS token (the standard Azure SharedAccessSignature scheme)."""
    encoded_uri = urllib.parse.quote(resource_uri, safe="")
    expiry = int(time.time() + ttl_seconds)
    string_to_sign = f"{encoded_uri}\n{expiry}".encode()
    signing_key = base64.b64decode(key)
    signature = base64.b64encode(hmac.new(signing_key, string_to_sign, hashlib.sha256).digest())
    encoded_signature = urllib.parse.quote(signature, safe="")
    token = f"SharedAccessSignature sr={encoded_uri}&sig={encoded_signature}&se={expiry}"
    if key_name:
        token += f"&skn={urllib.parse.quote(key_name, safe='')}"
    return token


def _auth_header() -> dict[str, str]:
    return {"Authorization": _generate_sas_token(HOSTNAME, _KEY_NAME, _KEY)}


client = httpx.Client(base_url=f"https://{HOSTNAME}", timeout=30.0)

mcp = FastMCP("azure-iot-hub")

_DEVICE_ID_DESC = "Azure IoT Hub device ID."
_MODULE_ID_DESC = "Module ID on the device."
_CONFIRM_DESC = "Must be explicitly set to True to perform this delete. Safety gate against accidental destructive calls."
_OVERWRITE_DESC = (
    "If False (default), fails if the resource already exists. Set True to replace/update it. "
    "Best-effort check (describe-then-create) -- IoT Hub's If-Match ETag header is for optimistic "
    "concurrency on updates, not create-only semantics."
)
_ETAG_DESC = "Optional ETag for optimistic concurrency -- fails if the resource was modified since you last read it."


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    params = kwargs.pop("params", {}) or {}
    params["api-version"] = API_VERSION
    headers = kwargs.pop("headers", {}) or {}
    headers.update(_auth_header())
    return client.request(method, path, params=params, headers=headers, **kwargs)


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"{context} ({resp.status_code}): {resp.text}")


def _require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(f"Refusing to {action} without confirm=True.")


def _create_or_replace(path: str, body: dict[str, Any], overwrite: bool, context: str) -> httpx.Response:
    if not overwrite:
        existing = _request("GET", path)
        if existing.status_code == 200:
            raise RuntimeError(f"{context} already exists (pass overwrite=True to replace it).")
        if existing.status_code != 404:
            _raise_for_status(existing, f"Failed to check existing {context}")
    resp = _request("PUT", path, json=body)
    _raise_for_status(resp, f"Failed to create/update {context}")
    return resp


# ---------------------------------------------------------------------------
# Device registry
# ---------------------------------------------------------------------------


@mcp.tool()
def list_devices(max_count: Annotated[int, Field(description="Maximum number of devices to return.", ge=1, le=1000)] = 100) -> dict[str, Any]:
    """List devices in the identity registry. For filtering, prefer query_devices instead.

    Wraps GET /devices.
    """
    resp = _request("GET", "/devices", params={"top": max_count})
    _raise_for_status(resp, "Failed to list devices")
    devices = resp.json()
    return {"devices": devices, "count": len(devices)}


@mcp.tool()
def get_device(device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)]) -> dict[str, Any]:
    """Fetch a device's identity (auth mechanism, status, connection state). Wraps GET /devices/{id}."""
    resp = _request("GET", f"/devices/{device_id}")
    _raise_for_status(resp, f"Failed to fetch device '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def create_device(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    auth_type: Annotated[Literal["sas", "selfSigned", "certificateAuthority", "none"], Field(description="Authentication mechanism.")] = "sas",
    primary_key: Annotated[str | None, Field(description="Base64 primary key (sas auth). Auto-generated by IoT Hub if omitted.")] = None,
    secondary_key: Annotated[str | None, Field(description="Base64 secondary key (sas auth).")] = None,
    primary_thumbprint: Annotated[str | None, Field(description="X.509 primary thumbprint (selfSigned auth).")] = None,
    secondary_thumbprint: Annotated[str | None, Field(description="X.509 secondary thumbprint (selfSigned auth).")] = None,
    status: Annotated[Literal["enabled", "disabled"], Field(description="Whether the device can connect.")] = "enabled",
    is_edge: Annotated[bool, Field(description="Whether this is an IoT Edge device.")] = False,
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Register a new device identity. Wraps PUT /devices/{id}."""
    auth: dict[str, Any] = {"type": auth_type}
    if auth_type == "sas":
        auth["symmetricKey"] = {"primaryKey": primary_key, "secondaryKey": secondary_key}
    elif auth_type == "selfSigned":
        auth["x509Thumbprint"] = {"primaryThumbprint": primary_thumbprint, "secondaryThumbprint": secondary_thumbprint}
    body = {
        "deviceId": device_id,
        "status": status,
        "authentication": auth,
        "capabilities": {"iotEdge": is_edge},
    }
    resp = _create_or_replace(f"/devices/{device_id}", body, overwrite, f"device '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def update_device(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    status: Annotated[Literal["enabled", "disabled"] | None, Field(description="Whether the device can connect.")] = None,
    status_reason: Annotated[str | None, Field(description="Reason for the status, up to 128 characters.")] = None,
    etag: Annotated[str | None, Field(description=_ETAG_DESC)] = None,
) -> dict[str, Any]:
    """Update a device's status. Wraps PUT /devices/{id} (full device fetched first, then patched fields applied)."""
    current = get_device(device_id)
    if status is not None:
        current["status"] = status
    if status_reason is not None:
        current["statusReason"] = status_reason
    headers = {"If-Match": f'"{etag}"'} if etag else {}
    resp = _request("PUT", f"/devices/{device_id}", json=current, headers=headers)
    _raise_for_status(resp, f"Failed to update device '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def delete_device(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
    etag: Annotated[str | None, Field(description="If provided, only delete if the device wasn't modified since this ETag. Omit to force delete.")] = None,
) -> dict[str, Any]:
    """Delete a device identity. Wraps DELETE /devices/{id}. Irreversible."""
    _require_confirm(confirm, f"delete device '{device_id}'")
    resp = _request("DELETE", f"/devices/{device_id}", headers={"If-Match": f'"{etag}"' if etag else "*"})
    _raise_for_status(resp, f"Failed to delete device '{device_id}'")
    return {"deviceId": device_id, "deleted": True}


@mcp.tool()
def query_devices(
    query: Annotated[str, Field(description='IoT Hub SQL-like query, e.g. "SELECT * FROM devices WHERE tags.location=\'lab-1\'".')],
    max_item_count: Annotated[int, Field(description="Maximum items per page.", ge=1, le=1000)] = 100,
    continuation_token: Annotated[str | None, Field(description="Continuation token from a previous call, to fetch the next page.")] = None,
) -> dict[str, Any]:
    """Query devices/twins using IoT Hub's query language. Wraps POST /devices/query.

    Returns:
        {"items": [...], "count": int, "continuation_token": str | None}
    """
    headers = {"x-ms-max-item-count": str(max_item_count)}
    if continuation_token:
        headers["x-ms-continuation"] = continuation_token
    resp = _request("POST", "/devices/query", json={"query": query}, headers=headers)
    _raise_for_status(resp, "Query failed")
    items = resp.json()
    return {"items": items, "count": len(items), "continuation_token": resp.headers.get("x-ms-continuation")}


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------


@mcp.tool()
def list_modules(device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)]) -> dict[str, Any]:
    """List module identities on a device. Wraps GET /devices/{deviceId}/modules."""
    resp = _request("GET", f"/devices/{device_id}/modules")
    _raise_for_status(resp, f"Failed to list modules on '{device_id}'")
    modules = resp.json()
    return {"deviceId": device_id, "modules": modules, "count": len(modules)}


@mcp.tool()
def get_module(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
) -> dict[str, Any]:
    """Fetch a module identity. Wraps GET /devices/{deviceId}/modules/{moduleId}."""
    resp = _request("GET", f"/devices/{device_id}/modules/{module_id}")
    _raise_for_status(resp, f"Failed to fetch module '{module_id}' on '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def create_module(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
    auth_type: Annotated[Literal["sas", "selfSigned", "certificateAuthority", "none"], Field(description="Authentication mechanism.")] = "sas",
    primary_key: Annotated[str | None, Field(description="Base64 primary key (sas auth).")] = None,
    secondary_key: Annotated[str | None, Field(description="Base64 secondary key (sas auth).")] = None,
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Register a new module identity on a device. Wraps PUT /devices/{deviceId}/modules/{moduleId}."""
    auth: dict[str, Any] = {"type": auth_type}
    if auth_type == "sas":
        auth["symmetricKey"] = {"primaryKey": primary_key, "secondaryKey": secondary_key}
    body = {"deviceId": device_id, "moduleId": module_id, "authentication": auth}
    resp = _create_or_replace(
        f"/devices/{device_id}/modules/{module_id}", body, overwrite, f"module '{module_id}' on '{device_id}'"
    )
    return dict(resp.json())


@mcp.tool()
def delete_module(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a module identity. Wraps DELETE /devices/{deviceId}/modules/{moduleId}. Irreversible."""
    _require_confirm(confirm, f"delete module '{module_id}' on device '{device_id}'")
    resp = _request("DELETE", f"/devices/{device_id}/modules/{module_id}", headers={"If-Match": "*"})
    _raise_for_status(resp, f"Failed to delete module '{module_id}' on '{device_id}'")
    return {"deviceId": device_id, "moduleId": module_id, "deleted": True}


# ---------------------------------------------------------------------------
# Device / module twins
# ---------------------------------------------------------------------------


@mcp.tool()
def get_device_twin(device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)]) -> dict[str, Any]:
    """Fetch a device's twin (tags, desired/reported properties). Wraps GET /twins/{id}."""
    resp = _request("GET", f"/twins/{device_id}")
    _raise_for_status(resp, f"Failed to fetch twin for '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def update_device_twin(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    tags: Annotated[dict[str, Any] | None, Field(description="Tags to merge in. Null values delete that key.")] = None,
    desired_properties: Annotated[dict[str, Any] | None, Field(description="Desired properties to merge in. Null values delete that key.")] = None,
    etag: Annotated[str | None, Field(description=_ETAG_DESC)] = None,
) -> dict[str, Any]:
    """Merge-update a device twin's tags and/or desired properties. Wraps PATCH /twins/{id}."""
    if tags is None and desired_properties is None:
        raise ValueError("Provide at least one of tags or desired_properties.")
    body: dict[str, Any] = {}
    if tags is not None:
        body["tags"] = tags
    if desired_properties is not None:
        body["properties"] = {"desired": desired_properties}
    headers = {"If-Match": f'"{etag}"'} if etag else {}
    resp = _request("PATCH", f"/twins/{device_id}", json=body, headers=headers)
    _raise_for_status(resp, f"Failed to update twin for '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def replace_device_twin(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    tags: Annotated[dict[str, Any] | None, Field(description="Full replacement tags object.")] = None,
    desired_properties: Annotated[dict[str, Any] | None, Field(description="Full replacement desired-properties object.")] = None,
    etag: Annotated[str | None, Field(description=_ETAG_DESC)] = None,
) -> dict[str, Any]:
    """Replace (not merge) a device twin's tags and desired properties. Wraps PUT /twins/{id}."""
    body: dict[str, Any] = {"tags": tags or {}, "properties": {"desired": desired_properties or {}}}
    headers = {"If-Match": f'"{etag}"'} if etag else {}
    resp = _request("PUT", f"/twins/{device_id}", json=body, headers=headers)
    _raise_for_status(resp, f"Failed to replace twin for '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def get_module_twin(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
) -> dict[str, Any]:
    """Fetch a module's twin. Wraps GET /twins/{deviceId}/modules/{moduleId}."""
    resp = _request("GET", f"/twins/{device_id}/modules/{module_id}")
    _raise_for_status(resp, f"Failed to fetch twin for module '{module_id}' on '{device_id}'")
    return dict(resp.json())


@mcp.tool()
def update_module_twin(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
    tags: Annotated[dict[str, Any] | None, Field(description="Tags to merge in.")] = None,
    desired_properties: Annotated[dict[str, Any] | None, Field(description="Desired properties to merge in.")] = None,
    etag: Annotated[str | None, Field(description=_ETAG_DESC)] = None,
) -> dict[str, Any]:
    """Merge-update a module twin's tags and/or desired properties. Wraps PATCH /twins/{deviceId}/modules/{moduleId}."""
    if tags is None and desired_properties is None:
        raise ValueError("Provide at least one of tags or desired_properties.")
    body: dict[str, Any] = {}
    if tags is not None:
        body["tags"] = tags
    if desired_properties is not None:
        body["properties"] = {"desired": desired_properties}
    headers = {"If-Match": f'"{etag}"'} if etag else {}
    resp = _request("PATCH", f"/twins/{device_id}/modules/{module_id}", json=body, headers=headers)
    _raise_for_status(resp, f"Failed to update twin for module '{module_id}' on '{device_id}'")
    return dict(resp.json())


# ---------------------------------------------------------------------------
# Direct methods
# ---------------------------------------------------------------------------


@mcp.tool()
def invoke_device_method(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    method_name: Annotated[str, Field(description="Name of the direct method to invoke.")],
    payload: Annotated[dict[str, Any] | None, Field(description="JSON payload for the method, up to 128KB.")] = None,
    connect_timeout_seconds: Annotated[int, Field(description="Seconds to wait for the device to come online.", ge=0, le=300)] = 30,
    response_timeout_seconds: Annotated[int, Field(description="Seconds to wait for the device's response.", ge=5, le=300)] = 30,
) -> dict[str, Any]:
    """Invoke a direct method on a device. Wraps POST /twins/{deviceId}/methods."""
    body = {
        "methodName": method_name,
        "payload": payload or {},
        "connectTimeoutInSeconds": connect_timeout_seconds,
        "responseTimeoutInSeconds": response_timeout_seconds,
    }
    resp = _request("POST", f"/twins/{device_id}/methods", json=body)
    _raise_for_status(resp, f"Direct method '{method_name}' on '{device_id}' failed")
    return dict(resp.json())


@mcp.tool()
def invoke_module_method(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    module_id: Annotated[str, Field(description=_MODULE_ID_DESC)],
    method_name: Annotated[str, Field(description="Name of the direct method to invoke.")],
    payload: Annotated[dict[str, Any] | None, Field(description="JSON payload for the method, up to 128KB.")] = None,
    connect_timeout_seconds: Annotated[int, Field(description="Seconds to wait for the module to come online.", ge=0, le=300)] = 30,
    response_timeout_seconds: Annotated[int, Field(description="Seconds to wait for the module's response.", ge=5, le=300)] = 30,
) -> dict[str, Any]:
    """Invoke a direct method on a module. Wraps POST /twins/{deviceId}/modules/{moduleId}/methods."""
    body = {
        "methodName": method_name,
        "payload": payload or {},
        "connectTimeoutInSeconds": connect_timeout_seconds,
        "responseTimeoutInSeconds": response_timeout_seconds,
    }
    resp = _request("POST", f"/twins/{device_id}/modules/{module_id}/methods", json=body)
    _raise_for_status(resp, f"Direct method '{method_name}' on module '{module_id}' of '{device_id}' failed")
    return dict(resp.json())


# ---------------------------------------------------------------------------
# Jobs (scheduled twin updates / direct methods at scale)
# ---------------------------------------------------------------------------


@mcp.tool()
def create_scheduled_job(
    job_id: Annotated[str, Field(description="Unique job ID you choose.")],
    job_type: Annotated[Literal["scheduleUpdateTwin", "scheduleDeviceMethod"], Field(description="What the job does.")],
    query_condition: Annotated[str, Field(description="IoT Hub query selecting target devices, e.g. \"deviceId IN ['a','b']\" or a tag/twin query.")],
    method_name: Annotated[str | None, Field(description="Required if job_type is scheduleDeviceMethod.")] = None,
    method_payload: Annotated[dict[str, Any] | None, Field(description="Payload for scheduleDeviceMethod.")] = None,
    twin_patch: Annotated[dict[str, Any] | None, Field(description="Twin patch (tags/properties.desired) for scheduleUpdateTwin.")] = None,
    start_time: Annotated[str | None, Field(description="ISO-8601 start time. Omit to start immediately.")] = None,
    max_execution_time_seconds: Annotated[int | None, Field(description="Timeout for the whole job.")] = None,
) -> dict[str, Any]:
    """Create a scheduled job to update twins or invoke a method across many devices. Wraps PUT /jobs/v2/{id}."""
    body: dict[str, Any] = {"jobId": job_id, "type": job_type, "queryCondition": query_condition}
    if job_type == "scheduleDeviceMethod":
        if not method_name:
            raise ValueError("method_name is required for job_type='scheduleDeviceMethod'.")
        body["cloudToDeviceMethod"] = {"methodName": method_name, "payload": method_payload or {}}
    else:
        body["updateTwin"] = twin_patch or {}
    if start_time:
        body["startTime"] = start_time
    if max_execution_time_seconds is not None:
        body["maxExecutionTimeInSeconds"] = max_execution_time_seconds
    resp = _request("PUT", f"/jobs/v2/{job_id}", json=body)
    _raise_for_status(resp, f"Failed to create job '{job_id}'")
    return dict(resp.json())


@mcp.tool()
def get_scheduled_job(job_id: Annotated[str, Field(description="Job ID.")]) -> dict[str, Any]:
    """Fetch a scheduled job's status and results. Wraps GET /jobs/v2/{id}."""
    resp = _request("GET", f"/jobs/v2/{job_id}")
    _raise_for_status(resp, f"Failed to fetch job '{job_id}'")
    return dict(resp.json())


@mcp.tool()
def query_scheduled_jobs(
    job_type: Annotated[str | None, Field(description="Filter by job type, e.g. 'scheduleUpdateTwin'.")] = None,
    job_status: Annotated[str | None, Field(description="Filter by status, e.g. 'completed', 'running', 'scheduled'.")] = None,
) -> dict[str, Any]:
    """List scheduled jobs, optionally filtered. Wraps GET /jobs/v2/query."""
    params: dict[str, Any] = {}
    if job_type:
        params["jobType"] = job_type
    if job_status:
        params["jobStatus"] = job_status
    resp = _request("GET", "/jobs/v2/query", params=params)
    _raise_for_status(resp, "Failed to query jobs")
    jobs = resp.json()
    return {"jobs": jobs, "count": len(jobs)}


@mcp.tool()
def cancel_scheduled_job(
    job_id: Annotated[str, Field(description="Job ID.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Cancel a scheduled job. Wraps POST /jobs/v2/{id}/cancel."""
    _require_confirm(confirm, f"cancel job '{job_id}'")
    resp = _request("POST", f"/jobs/v2/{job_id}/cancel")
    _raise_for_status(resp, f"Failed to cancel job '{job_id}'")
    return dict(resp.json())


# ---------------------------------------------------------------------------
# Cloud-to-device messaging
# ---------------------------------------------------------------------------


@mcp.tool()
def purge_c2d_message_queue(device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)]) -> dict[str, Any]:
    """Delete all pending cloud-to-device messages queued for a device. Wraps DELETE /devices/{deviceId}/commands."""
    resp = _request("DELETE", f"/devices/{device_id}/commands")
    _raise_for_status(resp, f"Failed to purge C2D queue for '{device_id}'")
    return {"deviceId": device_id, "purged": True}


def _cbs_authorize(connection: "proton.utils.BlockingConnection", hostname: str) -> None:
    audience = f"https://{hostname}"
    sas_token = _generate_sas_token(hostname, _KEY_NAME, _KEY)
    request = proton.Message()
    request.body = sas_token
    request.properties = {  # type: ignore[assignment]  # proton's stubs mistype this as None
        "operation": "put-token",
        "type": "servicebus.windows.net:sastoken",
        "name": audience,
    }
    rpc = proton.utils.SyncRequestResponse(connection, "$cbs")
    response = rpc.call(request)
    status_code = (response.properties or {}).get("status-code")  # type: ignore[call-overload]
    if status_code not in (200, 202):
        raise RuntimeError(f"CBS authorization failed: {response.properties}")


@mcp.tool()
def send_c2d_message(
    device_id: Annotated[str, Field(description=_DEVICE_ID_DESC)],
    payload: Annotated[str, Field(description="Message payload (UTF-8 text or JSON string).")],
    content_type: Annotated[str | None, Field(description="e.g. 'application/json'.")] = None,
    correlation_id: Annotated[str | None, Field(description="Correlation ID for request/response patterns.")] = None,
    message_id: Annotated[str | None, Field(description="Message ID. Auto-generated if omitted.")] = None,
    app_properties: Annotated[dict[str, str] | None, Field(description="Custom application properties.")] = None,
) -> dict[str, Any]:
    """Send a cloud-to-device message. Wraps the AMQP C2D send (there is no REST equivalent for
    sending -- only the REST API's feedback/receipt operations are REST; the send itself is
    AMQP-only in the Azure IoT Hub service API).

    Not covered by this repo's automated real-instance testing: only a local
    fake AMQP endpoint (CBS handshake + message receipt) is exercised in CI,
    not genuine Azure IoT Hub business logic. Verify against a real hub before
    relying on this in production.
    """
    # Read fresh on every call (not module-level constants) so tests can point
    # this at a local fake endpoint without needing to reimport the module.
    hostname = os.getenv("AZURE_IOT_HUB_AMQP_HOSTNAME_OVERRIDE") or HOSTNAME
    amqp_port = int(os.getenv("AZURE_IOT_HUB_AMQP_PORT", "5671"))
    use_tls = os.getenv("AZURE_IOT_HUB_AMQP_USE_TLS", "true").lower() == "true"
    url = f"amqps://{hostname}:{amqp_port}" if use_tls else f"amqp://{hostname}:{amqp_port}"
    connection = proton.utils.BlockingConnection(url, timeout=15)
    try:
        _cbs_authorize(connection, HOSTNAME)
        sender = connection.create_sender("/messages/devicebound")
        message = proton.Message()
        message.address = f"/devices/{device_id}/messages/devicebound"
        message.body = payload
        if message_id:
            message.id = message_id
        if correlation_id:
            message.correlation_id = correlation_id
        if content_type:
            message.content_type = content_type
        if app_properties:
            message.properties = app_properties  # type: ignore[assignment]  # proton's stubs mistype this as None
        sender.send(message)
    finally:
        connection.close()
    return {"deviceId": device_id, "sent": True}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@mcp.tool()
def get_device_statistics() -> dict[str, Any]:
    """Get identity-registry statistics (total/enabled/disabled device counts). Wraps GET /statistics/devices."""
    resp = _request("GET", "/statistics/devices")
    _raise_for_status(resp, "Failed to fetch device statistics")
    return dict(resp.json())


@mcp.tool()
def get_service_statistics() -> dict[str, Any]:
    """Get service statistics (e.g. connected device count). Wraps GET /statistics/service."""
    resp = _request("GET", "/statistics/service")
    _raise_for_status(resp, "Failed to fetch service statistics")
    return dict(resp.json())


_Transport = Literal["stdio", "http", "sse", "streamable-http"]


def _get_mcp_init_vars() -> tuple[_Transport, str, int]:
    """Get MCP initialization variables from environment configuration.

    Returns:
        tuple[_Transport, str, int]: transport, host, port.
    """
    raw_transport = os.getenv("TRANSPORT") or "stdio"
    if raw_transport in ["stdio", "<TRANSPORT>", "", "-", "null"]:
        logger.info("MCP init: transport=stdio")
        return ("stdio", "", 0)

    transport: _Transport
    if raw_transport == "http":
        transport = "http"
    elif raw_transport == "sse":
        transport = "sse"
    elif raw_transport == "streamable-http":
        transport = "streamable-http"
    else:
        raise ValueError(
            f"Invalid TRANSPORT env variable: '{raw_transport}' - must be one of stdio, http, sse, streamable-http"
        )

    host = os.getenv("HOST") or "127.0.0.1"
    port_str = os.getenv("HOST_PORT") or "8000"
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(f"Invalid HOST_PORT env variable: '{port_str}' - must be a valid integer")
    logger.info(f"MCP init: transport={transport}, host={host}, port={port}")
    return (transport, host, port)


def main() -> None:
    transport, host, port = _get_mcp_init_vars()
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=transport, transport_options={"host": host, "port": port})


if __name__ == "__main__":
    main()
