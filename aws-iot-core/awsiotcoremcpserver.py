import json
import logging
import os
from typing import Annotated, Any, Literal

import boto3
from botocore.exceptions import ClientError
from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

client = boto3.client("iot")
data_client = boto3.client("iot-data")

mcp = FastMCP("aws-iot-core")

_THING_NAME_DESC = "AWS IoT thing name."
_CONFIRM_DESC = "Must be explicitly set to True to perform this delete. Safety gate against accidental destructive calls."
_OVERWRITE_DESC = (
    "If False (default), fails if the resource already exists. Set True to replace/update it. "
    "Best-effort check (describe-then-create) -- most IoT Core write APIs have no conditional-write header."
)


def _err(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Message", str(e))


def _require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(f"Refusing to {action} without confirm=True.")


def _strip_response_metadata(resp: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in resp.items() if k != "ResponseMetadata"}


# ---------------------------------------------------------------------------
# Things
# ---------------------------------------------------------------------------


@mcp.tool()
def list_things(
    thing_type_name: Annotated[str | None, Field(description="Filter to things of this type.")] = None,
    attribute_name: Annotated[str | None, Field(description="Filter by attribute name (requires attribute_value too).")] = None,
    attribute_value: Annotated[str | None, Field(description="Filter by attribute value.")] = None,
    thing_group_name: Annotated[str | None, Field(description="Filter to things in this thing group.")] = None,
    max_results: Annotated[int, Field(description="Maximum number of things to return.", ge=1, le=250)] = 50,
) -> dict[str, Any]:
    """List things (devices) in the registry, optionally filtered.

    Wraps ListThings.
    """
    params: dict[str, Any] = {"maxResults": max_results}
    if thing_type_name:
        params["thingTypeName"] = thing_type_name
    if attribute_name:
        params["attributeName"] = attribute_name
    if attribute_value is not None:
        params["attributeValue"] = attribute_value
    if thing_group_name:
        params["thingGroupName"] = thing_group_name
    try:
        resp = client.list_things(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list things: {_err(e)}") from e
    things = resp.get("things", [])
    return {"things": things, "count": len(things)}


@mcp.tool()
def search_things(
    query_string: Annotated[str, Field(description='Fleet indexing query, e.g. \'attributes.location:"lab-1"\'.')],
    index_name: Annotated[str | None, Field(description="Index to search. Omit for the default thing index.")] = None,
    max_results: Annotated[int, Field(description="Maximum number of things to return.", ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """Search things via AWS IoT fleet indexing.

    Wraps SearchIndex. Requires fleet indexing to be enabled on the account
    (UpdateIndexingConfiguration) -- most self-serve accounts have it on by
    default for the registry index.
    """
    params: dict[str, Any] = {"queryString": query_string, "maxResults": max_results}
    if index_name:
        params["indexName"] = index_name
    try:
        resp = client.search_index(**params)
    except ClientError as e:
        raise RuntimeError(f"Fleet index search failed: {_err(e)}") from e
    things = resp.get("things", [])
    return {"things": things, "count": len(things)}


@mcp.tool()
def get_thing(thing_name: Annotated[str, Field(description=_THING_NAME_DESC)]) -> dict[str, Any]:
    """Fetch a thing's attributes, type, and version. Wraps DescribeThing."""
    try:
        resp = client.describe_thing(thingName=thing_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch thing '{thing_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def create_thing(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    thing_type_name: Annotated[str | None, Field(description="Thing type to associate.")] = None,
    attributes: Annotated[dict[str, str] | None, Field(description="Key/value attributes (up to 50, AWS-imposed limit).")] = None,
    billing_group_name: Annotated[str | None, Field(description="Billing group to associate.")] = None,
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Register a new thing in the registry. Wraps CreateThing."""
    if not overwrite:
        try:
            client.describe_thing(thingName=thing_name)
            raise RuntimeError(f"Thing '{thing_name}' already exists (pass overwrite=True to update it).")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise RuntimeError(f"Failed to check existing thing '{thing_name}': {_err(e)}") from e

    params: dict[str, Any] = {"thingName": thing_name}
    if thing_type_name:
        params["thingTypeName"] = thing_type_name
    if attributes:
        params["attributePayload"] = {"attributes": attributes}
    if billing_group_name:
        params["billingGroupName"] = billing_group_name
    try:
        resp = client.create_thing(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to create thing '{thing_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def update_thing(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    attributes: Annotated[dict[str, str] | None, Field(description="Attributes to set. Null values delete that attribute.")] = None,
    thing_type_name: Annotated[str | None, Field(description="New thing type to associate.")] = None,
    remove_thing_type: Annotated[bool, Field(description="Detach the current thing type.")] = False,
    attributes_merge: Annotated[bool, Field(description="If True (default), merge with existing attributes. If False, replace them entirely.")] = True,
) -> dict[str, Any]:
    """Update a thing's attributes and/or type. Wraps UpdateThing."""
    params: dict[str, Any] = {"thingName": thing_name}
    if attributes is not None:
        params["attributePayload"] = {"attributes": attributes, "merge": attributes_merge}
    if thing_type_name:
        params["thingTypeName"] = thing_type_name
    if remove_thing_type:
        params["removeThingType"] = True
    try:
        client.update_thing(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to update thing '{thing_name}': {_err(e)}") from e
    return {"thingName": thing_name, "updated": True}


@mcp.tool()
def delete_thing(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a thing from the registry. Wraps DeleteThing. Irreversible."""
    _require_confirm(confirm, f"delete thing '{thing_name}'")
    try:
        client.delete_thing(thingName=thing_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete thing '{thing_name}': {_err(e)}") from e
    return {"thingName": thing_name, "deleted": True}


# ---------------------------------------------------------------------------
# Thing Types
# ---------------------------------------------------------------------------


@mcp.tool()
def list_thing_types(thing_type_name: Annotated[str | None, Field(description="Filter by name prefix.")] = None) -> dict[str, Any]:
    """List thing types. Wraps ListThingTypes."""
    params: dict[str, Any] = {}
    if thing_type_name:
        params["thingTypeName"] = thing_type_name
    try:
        resp = client.list_thing_types(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list thing types: {_err(e)}") from e
    types_ = resp.get("thingTypes", [])
    return {"thingTypes": types_, "count": len(types_)}


@mcp.tool()
def get_thing_type(thing_type_name: Annotated[str, Field(description="Thing type name.")]) -> dict[str, Any]:
    """Fetch a thing type's definition. Wraps DescribeThingType."""
    try:
        resp = client.describe_thing_type(thingTypeName=thing_type_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch thing type '{thing_type_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def create_thing_type(
    thing_type_name: Annotated[str, Field(description="Thing type name.")],
    description: Annotated[str | None, Field(description="Description.")] = None,
    searchable_attributes: Annotated[list[str] | None, Field(description="Attribute names to make searchable (up to 3, AWS-imposed limit).")] = None,
) -> dict[str, Any]:
    """Create a thing type. Wraps CreateThingType.

    Thing types are immutable once created except for deprecation -- there is
    no update/overwrite operation in the AWS API.
    """
    properties: dict[str, Any] = {}
    if description:
        properties["thingTypeDescription"] = description
    if searchable_attributes:
        properties["searchableAttributes"] = searchable_attributes
    params: dict[str, Any] = {"thingTypeName": thing_type_name}
    if properties:
        params["thingTypeProperties"] = properties
    try:
        resp = client.create_thing_type(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to create thing type '{thing_type_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def deprecate_thing_type(
    thing_type_name: Annotated[str, Field(description="Thing type name.")],
    undo: Annotated[bool, Field(description="If True, un-deprecate instead.")] = False,
) -> dict[str, Any]:
    """Deprecate (or un-deprecate) a thing type. Wraps DeprecateThingType."""
    try:
        client.deprecate_thing_type(thingTypeName=thing_type_name, undoDeprecate=undo)
    except ClientError as e:
        raise RuntimeError(f"Failed to deprecate thing type '{thing_type_name}': {_err(e)}") from e
    return {"thingTypeName": thing_type_name, "deprecated": not undo}


@mcp.tool()
def delete_thing_type(
    thing_type_name: Annotated[str, Field(description="Thing type name.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a thing type. Wraps DeleteThingType. Irreversible.

    AWS requires the type to be deprecated first, and (in real AWS, not
    necessarily in test environments) waits ~5 minutes after deprecation
    before allowing deletion.
    """
    _require_confirm(confirm, f"delete thing type '{thing_type_name}'")
    try:
        client.delete_thing_type(thingTypeName=thing_type_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete thing type '{thing_type_name}': {_err(e)}") from e
    return {"thingTypeName": thing_type_name, "deleted": True}


# ---------------------------------------------------------------------------
# Thing Groups
# ---------------------------------------------------------------------------


@mcp.tool()
def list_thing_groups(
    parent_group: Annotated[str | None, Field(description="Filter to children of this group.")] = None,
    name_prefix_filter: Annotated[str | None, Field(description="Filter by name prefix.")] = None,
) -> dict[str, Any]:
    """List thing groups. Wraps ListThingGroups."""
    params: dict[str, Any] = {}
    if parent_group:
        params["parentGroup"] = parent_group
    if name_prefix_filter:
        params["namePrefixFilter"] = name_prefix_filter
    try:
        resp = client.list_thing_groups(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list thing groups: {_err(e)}") from e
    groups = resp.get("thingGroups", [])
    return {"thingGroups": groups, "count": len(groups)}


@mcp.tool()
def get_thing_group(thing_group_name: Annotated[str, Field(description="Thing group name.")]) -> dict[str, Any]:
    """Fetch a thing group's definition. Wraps DescribeThingGroup."""
    try:
        resp = client.describe_thing_group(thingGroupName=thing_group_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch thing group '{thing_group_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def create_thing_group(
    thing_group_name: Annotated[str, Field(description="Thing group name.")],
    parent_group_name: Annotated[str | None, Field(description="Parent group, for hierarchical grouping.")] = None,
    attributes: Annotated[dict[str, str] | None, Field(description="Group attributes.")] = None,
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Create a thing group. Wraps CreateThingGroup."""
    if not overwrite:
        try:
            client.describe_thing_group(thingGroupName=thing_group_name)
            raise RuntimeError(f"Thing group '{thing_group_name}' already exists (pass overwrite=True to replace it).")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise RuntimeError(f"Failed to check existing thing group '{thing_group_name}': {_err(e)}") from e

    params: dict[str, Any] = {"thingGroupName": thing_group_name}
    if parent_group_name:
        params["parentGroupName"] = parent_group_name
    if attributes:
        params["thingGroupProperties"] = {"attributePayload": {"attributes": attributes}}
    try:
        resp = client.create_thing_group(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to create thing group '{thing_group_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def delete_thing_group(
    thing_group_name: Annotated[str, Field(description="Thing group name.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a thing group. Wraps DeleteThingGroup. Irreversible. Fails if it has child groups."""
    _require_confirm(confirm, f"delete thing group '{thing_group_name}'")
    try:
        client.delete_thing_group(thingGroupName=thing_group_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete thing group '{thing_group_name}': {_err(e)}") from e
    return {"thingGroupName": thing_group_name, "deleted": True}


@mcp.tool()
def modify_thing_group_membership(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    thing_group_name: Annotated[str, Field(description="Thing group name.")],
    action: Annotated[Literal["add", "remove"], Field(description="Add the thing to, or remove it from, the group.")],
) -> dict[str, Any]:
    """Add or remove a thing from a thing group. Wraps AddThingToThingGroup / RemoveThingFromThingGroup."""
    try:
        if action == "add":
            client.add_thing_to_thing_group(thingGroupName=thing_group_name, thingName=thing_name)
        else:
            client.remove_thing_from_thing_group(thingGroupName=thing_group_name, thingName=thing_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to {action} thing '{thing_name}' {'to' if action == 'add' else 'from'} group '{thing_group_name}': {_err(e)}") from e
    return {"thingName": thing_name, "thingGroupName": thing_group_name, "action": action}


@mcp.tool()
def list_things_in_thing_group(thing_group_name: Annotated[str, Field(description="Thing group name.")]) -> dict[str, Any]:
    """List things that belong to a thing group. Wraps ListThingsInThingGroup."""
    try:
        resp = client.list_things_in_thing_group(thingGroupName=thing_group_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to list things in group '{thing_group_name}': {_err(e)}") from e
    names = resp.get("things", [])
    return {"thingGroupName": thing_group_name, "things": names, "count": len(names)}


# ---------------------------------------------------------------------------
# Device Shadows (data plane)
# ---------------------------------------------------------------------------


@mcp.tool()
def get_thing_shadow(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    shadow_name: Annotated[str | None, Field(description="Named shadow. Omit for the classic (unnamed) shadow.")] = None,
) -> dict[str, Any]:
    """Read a thing's shadow document. Wraps GetThingShadow."""
    params: dict[str, Any] = {"thingName": thing_name}
    if shadow_name:
        params["shadowName"] = shadow_name
    try:
        resp = data_client.get_thing_shadow(**params)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return {}
        raise RuntimeError(f"Failed to fetch shadow for '{thing_name}': {_err(e)}") from e
    payload: dict[str, Any] = json.loads(resp["payload"].read())
    return payload


@mcp.tool()
def update_thing_shadow(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    desired: Annotated[dict[str, Any] | None, Field(description="Desired state to merge in. Null-valued keys delete that field.")] = None,
    reported: Annotated[dict[str, Any] | None, Field(description="Reported state to merge in.")] = None,
    shadow_name: Annotated[str | None, Field(description="Named shadow. Omit for the classic (unnamed) shadow.")] = None,
) -> dict[str, Any]:
    """Merge-update a thing's shadow state. Wraps UpdateThingShadow.

    Shadow updates are always a JSON-merge-patch against the existing
    document (per the shadow protocol itself) -- there is no separate
    create-vs-replace distinction to gate here.
    """
    if desired is None and reported is None:
        raise ValueError("Provide at least one of desired or reported.")
    state: dict[str, Any] = {}
    if desired is not None:
        state["desired"] = desired
    if reported is not None:
        state["reported"] = reported
    params: dict[str, Any] = {"thingName": thing_name, "payload": json.dumps({"state": state})}
    if shadow_name:
        params["shadowName"] = shadow_name
    try:
        resp = data_client.update_thing_shadow(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to update shadow for '{thing_name}': {_err(e)}") from e
    payload: dict[str, Any] = json.loads(resp["payload"].read())
    return payload


@mcp.tool()
def delete_thing_shadow(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    shadow_name: Annotated[str | None, Field(description="Named shadow. Omit for the classic (unnamed) shadow.")] = None,
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a thing's shadow document. Wraps DeleteThingShadow. Irreversible."""
    _require_confirm(confirm, f"delete shadow for '{thing_name}'")
    params: dict[str, Any] = {"thingName": thing_name}
    if shadow_name:
        params["shadowName"] = shadow_name
    try:
        data_client.delete_thing_shadow(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete shadow for '{thing_name}': {_err(e)}") from e
    return {"thingName": thing_name, "shadowName": shadow_name, "deleted": True}


@mcp.tool()
def list_named_shadows_for_thing(thing_name: Annotated[str, Field(description=_THING_NAME_DESC)]) -> dict[str, Any]:
    """List named (non-classic) shadows for a thing. Wraps ListNamedShadowsForThing."""
    try:
        resp = data_client.list_named_shadows_for_thing(thingName=thing_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to list named shadows for '{thing_name}': {_err(e)}") from e
    names = resp.get("results", [])
    return {"thingName": thing_name, "shadowNames": names, "count": len(names)}


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


@mcp.tool()
def publish_message(
    topic: Annotated[str, Field(description="MQTT topic to publish to.")],
    payload: Annotated[str, Field(description="Message payload (UTF-8 text or JSON string).")],
    qos: Annotated[int, Field(description="0 or 1 (IoT Core does not support QoS 2).", ge=0, le=1)] = 0,
) -> dict[str, Any]:
    """Publish a message to the device fleet. Wraps the IoT Data Plane's Publish."""
    try:
        data_client.publish(topic=topic, qos=qos, payload=payload.encode("utf-8"))
    except ClientError as e:
        raise RuntimeError(f"Failed to publish to '{topic}': {_err(e)}") from e
    return {"topic": topic, "qos": qos, "published": True}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@mcp.tool()
def list_jobs(
    status: Annotated[Literal["IN_PROGRESS", "CANCELED", "COMPLETED", "DELETION_IN_PROGRESS"] | None, Field(description="Filter by job status.")] = None,
    thing_group_name: Annotated[str | None, Field(description="Filter to jobs targeting this thing group.")] = None,
    max_results: Annotated[int, Field(description="Maximum number of jobs to return.", ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """List fleet jobs. Wraps ListJobs."""
    params: dict[str, Any] = {"maxResults": max_results}
    if status:
        params["status"] = status
    if thing_group_name:
        params["thingGroupName"] = thing_group_name
    try:
        resp = client.list_jobs(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list jobs: {_err(e)}") from e
    jobs = resp.get("jobs", [])
    return {"jobs": jobs, "count": len(jobs)}


@mcp.tool()
def get_job(job_id: Annotated[str, Field(description="Job ID.")]) -> dict[str, Any]:
    """Fetch a job's definition and status. Wraps DescribeJob."""
    try:
        resp = client.describe_job(jobId=job_id)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch job '{job_id}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def create_job(
    job_id: Annotated[str, Field(description="Unique job ID you choose.")],
    thing_arns: Annotated[list[str], Field(description="Thing or thing-group ARNs to target.")],
    document: Annotated[dict[str, Any], Field(description="Job document (arbitrary JSON) sent to targeted devices.")],
    description: Annotated[str | None, Field(description="Human-readable description.")] = None,
    target_selection: Annotated[Literal["CONTINUOUS", "SNAPSHOT"], Field(description="CONTINUOUS also targets devices added to the group later.")] = "SNAPSHOT",
) -> dict[str, Any]:
    """Create a fleet job (e.g. an OTA update or a remote command). Wraps CreateJob."""
    try:
        resp = client.create_job(
            jobId=job_id,
            targets=thing_arns,
            document=json.dumps(document),
            targetSelection=target_selection,
            **({"description": description} if description else {}),
        )
    except ClientError as e:
        raise RuntimeError(f"Failed to create job '{job_id}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def cancel_job(
    job_id: Annotated[str, Field(description="Job ID.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
    comment: Annotated[str | None, Field(description="Reason for cancellation.")] = None,
    force: Annotated[bool, Field(description="Cancel even if executions are already in progress on some devices.")] = False,
) -> dict[str, Any]:
    """Cancel a job. Wraps CancelJob."""
    _require_confirm(confirm, f"cancel job '{job_id}'")
    params: dict[str, Any] = {"jobId": job_id, "force": force}
    if comment:
        params["comment"] = comment
    try:
        client.cancel_job(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to cancel job '{job_id}': {_err(e)}") from e
    return {"jobId": job_id, "canceled": True}


@mcp.tool()
def delete_job(
    job_id: Annotated[str, Field(description="Job ID.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
    force: Annotated[bool, Field(description="Delete even if the job is IN_PROGRESS.")] = False,
) -> dict[str, Any]:
    """Delete a job. Wraps DeleteJob. Irreversible."""
    _require_confirm(confirm, f"delete job '{job_id}'")
    try:
        client.delete_job(jobId=job_id, force=force)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete job '{job_id}': {_err(e)}") from e
    return {"jobId": job_id, "deleted": True}


@mcp.tool()
def list_job_executions_for_job(
    job_id: Annotated[str, Field(description="Job ID.")],
    status: Annotated[str | None, Field(description="Filter by execution status, e.g. 'FAILED', 'SUCCEEDED', 'IN_PROGRESS'.")] = None,
) -> dict[str, Any]:
    """List per-device execution status for a job. Wraps ListJobExecutionsForJob."""
    params: dict[str, Any] = {"jobId": job_id}
    if status:
        params["status"] = status
    try:
        resp = client.list_job_executions_for_job(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list executions for job '{job_id}': {_err(e)}") from e
    executions = resp.get("executionSummaries", [])
    return {"jobId": job_id, "executions": executions, "count": len(executions)}


@mcp.tool()
def list_job_executions_for_thing(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    status: Annotated[str | None, Field(description="Filter by execution status.")] = None,
) -> dict[str, Any]:
    """List job executions for a specific thing. Wraps ListJobExecutionsForThing."""
    params: dict[str, Any] = {"thingName": thing_name}
    if status:
        params["status"] = status
    try:
        resp = client.list_job_executions_for_thing(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list job executions for '{thing_name}': {_err(e)}") from e
    executions = resp.get("executionSummaries", [])
    return {"thingName": thing_name, "executions": executions, "count": len(executions)}


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


@mcp.tool()
def create_keys_and_certificate(
    set_as_active: Annotated[bool, Field(description="Activate the certificate immediately.")] = True,
) -> dict[str, Any]:
    """Generate a new X.509 certificate and RSA key pair. Wraps CreateKeysAndCertificate.

    The private key is returned only in this response -- AWS does not store
    it and cannot regenerate it. Capture it immediately.
    """
    try:
        resp = client.create_keys_and_certificate(setAsActive=set_as_active)
    except ClientError as e:
        raise RuntimeError(f"Failed to create certificate: {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def get_certificate(certificate_id: Annotated[str, Field(description="Certificate ID.")]) -> dict[str, Any]:
    """Fetch certificate metadata (not the key material). Wraps DescribeCertificate."""
    try:
        resp = client.describe_certificate(certificateId=certificate_id)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch certificate '{certificate_id}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def list_certificates(page_size: Annotated[int, Field(description="Maximum number of certificates to return.", ge=1, le=250)] = 50) -> dict[str, Any]:
    """List certificates in this account. Wraps ListCertificates."""
    try:
        resp = client.list_certificates(pageSize=page_size)
    except ClientError as e:
        raise RuntimeError(f"Failed to list certificates: {_err(e)}") from e
    certs = resp.get("certificates", [])
    return {"certificates": certs, "count": len(certs)}


@mcp.tool()
def set_certificate_status(
    certificate_id: Annotated[str, Field(description="Certificate ID.")],
    status: Annotated[Literal["ACTIVE", "INACTIVE", "REVOKED"], Field(description="New status.")],
) -> dict[str, Any]:
    """Change a certificate's status. Wraps UpdateCertificate."""
    try:
        client.update_certificate(certificateId=certificate_id, newStatus=status)
    except ClientError as e:
        raise RuntimeError(f"Failed to update certificate '{certificate_id}': {_err(e)}") from e
    return {"certificateId": certificate_id, "status": status}


@mcp.tool()
def delete_certificate(
    certificate_id: Annotated[str, Field(description="Certificate ID.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
    force_delete: Annotated[bool, Field(description="Delete even if the certificate is still ACTIVE.")] = False,
) -> dict[str, Any]:
    """Delete a certificate. Wraps DeleteCertificate. Irreversible."""
    _require_confirm(confirm, f"delete certificate '{certificate_id}'")
    try:
        client.delete_certificate(certificateId=certificate_id, forceDelete=force_delete)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete certificate '{certificate_id}': {_err(e)}") from e
    return {"certificateId": certificate_id, "deleted": True}


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@mcp.tool()
def create_policy(
    policy_name: Annotated[str, Field(description="Policy name.")],
    policy_document: Annotated[dict[str, Any], Field(description="IAM-style policy document JSON.")],
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Create an IoT policy, or add a new default version to an existing one with overwrite=True.

    Wraps CreatePolicy (new policy) / CreatePolicyVersion (existing policy).
    """
    exists = True
    try:
        client.get_policy(policyName=policy_name)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise RuntimeError(f"Failed to check existing policy '{policy_name}': {_err(e)}") from e
        exists = False

    if exists and not overwrite:
        raise RuntimeError(f"Policy '{policy_name}' already exists (pass overwrite=True to add a new version).")

    try:
        if exists:
            resp = client.create_policy_version(
                policyName=policy_name, policyDocument=json.dumps(policy_document), setAsDefault=True
            )
        else:
            resp = client.create_policy(policyName=policy_name, policyDocument=json.dumps(policy_document))
    except ClientError as e:
        raise RuntimeError(f"Failed to create policy '{policy_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def get_policy(policy_name: Annotated[str, Field(description="Policy name.")]) -> dict[str, Any]:
    """Fetch a policy's current default document. Wraps GetPolicy."""
    try:
        resp = client.get_policy(policyName=policy_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch policy '{policy_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def list_policies() -> dict[str, Any]:
    """List all IoT policies in this account. Wraps ListPolicies."""
    try:
        resp = client.list_policies()
    except ClientError as e:
        raise RuntimeError(f"Failed to list policies: {_err(e)}") from e
    policies = resp.get("policies", [])
    return {"policies": policies, "count": len(policies)}


@mcp.tool()
def delete_policy(
    policy_name: Annotated[str, Field(description="Policy name.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a policy. Wraps DeletePolicy. Irreversible. Fails if still attached to any certificate.

    AWS also refuses to delete a policy with more than one version -- this
    cleans up non-default versions first (DeletePolicyVersion) so the delete
    just works regardless of how many times the policy was updated.
    """
    _require_confirm(confirm, f"delete policy '{policy_name}'")
    try:
        versions = client.list_policy_versions(policyName=policy_name).get("policyVersions", [])
        for v in versions:
            if not v.get("isDefaultVersion"):
                client.delete_policy_version(policyName=policy_name, policyVersionId=v["versionId"])
        client.delete_policy(policyName=policy_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete policy '{policy_name}': {_err(e)}") from e
    return {"policyName": policy_name, "deleted": True}


@mcp.tool()
def modify_policy_attachment(
    policy_name: Annotated[str, Field(description="Policy name.")],
    target: Annotated[str, Field(description="Target ARN (typically a certificate ARN).")],
    action: Annotated[Literal["attach", "detach"], Field(description="Attach or detach the policy.")],
) -> dict[str, Any]:
    """Attach or detach a policy to/from a certificate. Wraps AttachPolicy / DetachPolicy."""
    try:
        if action == "attach":
            client.attach_policy(policyName=policy_name, target=target)
        else:
            client.detach_policy(policyName=policy_name, target=target)
    except ClientError as e:
        raise RuntimeError(f"Failed to {action} policy '{policy_name}' {'to' if action == 'attach' else 'from'} '{target}': {_err(e)}") from e
    return {"policyName": policy_name, "target": target, "action": action}


@mcp.tool()
def modify_thing_principal(
    thing_name: Annotated[str, Field(description=_THING_NAME_DESC)],
    principal: Annotated[str, Field(description="Principal ARN (typically a certificate ARN).")],
    action: Annotated[Literal["attach", "detach"], Field(description="Attach or detach the principal.")],
) -> dict[str, Any]:
    """Attach or detach a certificate (principal) to/from a thing. Wraps AttachThingPrincipal / DetachThingPrincipal."""
    try:
        if action == "attach":
            client.attach_thing_principal(thingName=thing_name, principal=principal)
        else:
            client.detach_thing_principal(thingName=thing_name, principal=principal)
    except ClientError as e:
        raise RuntimeError(f"Failed to {action} principal for thing '{thing_name}': {_err(e)}") from e
    return {"thingName": thing_name, "principal": principal, "action": action}


@mcp.tool()
def list_thing_principals(thing_name: Annotated[str, Field(description=_THING_NAME_DESC)]) -> dict[str, Any]:
    """List certificates (principals) attached to a thing. Wraps ListThingPrincipals."""
    try:
        resp = client.list_thing_principals(thingName=thing_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to list principals for '{thing_name}': {_err(e)}") from e
    principals = resp.get("principals", [])
    return {"thingName": thing_name, "principals": principals, "count": len(principals)}


@mcp.tool()
def list_principal_things(principal: Annotated[str, Field(description="Principal ARN (typically a certificate ARN).")]) -> dict[str, Any]:
    """List things a certificate (principal) is attached to. Wraps ListPrincipalThings."""
    try:
        resp = client.list_principal_things(principal=principal)
    except ClientError as e:
        raise RuntimeError(f"Failed to list things for principal '{principal}': {_err(e)}") from e
    things = resp.get("things", [])
    return {"principal": principal, "things": things, "count": len(things)}


# ---------------------------------------------------------------------------
# Rules Engine
# ---------------------------------------------------------------------------


@mcp.tool()
def list_topic_rules(topic: Annotated[str | None, Field(description="Filter to rules matching this topic.")] = None) -> dict[str, Any]:
    """List message-routing rules. Wraps ListTopicRules."""
    params: dict[str, Any] = {}
    if topic:
        params["topic"] = topic
    try:
        resp = client.list_topic_rules(**params)
    except ClientError as e:
        raise RuntimeError(f"Failed to list topic rules: {_err(e)}") from e
    rules = resp.get("rules", [])
    return {"rules": rules, "count": len(rules)}


@mcp.tool()
def get_topic_rule(rule_name: Annotated[str, Field(description="Rule name.")]) -> dict[str, Any]:
    """Fetch a rule's SQL and actions. Wraps GetTopicRule."""
    try:
        resp = client.get_topic_rule(ruleName=rule_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch topic rule '{rule_name}': {_err(e)}") from e
    return _strip_response_metadata(resp)


@mcp.tool()
def put_topic_rule(
    rule_name: Annotated[str, Field(description="Rule name.")],
    sql: Annotated[str, Field(description="IoT SQL statement, e.g. \"SELECT * FROM 'devices/+/telemetry'\".")],
    actions: Annotated[list[dict[str, Any]], Field(description="Raw AWS action objects, e.g. [{'lambda': {'functionArn': '...'}}].")],
    description: Annotated[str | None, Field(description="Description.")] = None,
    sql_version: Annotated[str, Field(description="IoT SQL version.")] = "2016-03-23",
    overwrite: Annotated[bool, Field(description=_OVERWRITE_DESC)] = False,
) -> dict[str, Any]:
    """Create or replace a rule. Wraps CreateTopicRule / ReplaceTopicRule."""
    payload = {
        "sql": sql,
        "actions": actions,
        "awsIotSqlVersion": sql_version,
        **({"description": description} if description else {}),
    }
    try:
        if overwrite:
            client.replace_topic_rule(ruleName=rule_name, topicRulePayload=payload)
        else:
            client.create_topic_rule(ruleName=rule_name, topicRulePayload=payload)
    except ClientError as e:
        raise RuntimeError(f"Failed to {'replace' if overwrite else 'create'} topic rule '{rule_name}': {_err(e)}") from e
    return {"ruleName": rule_name, "sql": sql, "actionCount": len(actions)}


@mcp.tool()
def set_topic_rule_enabled(
    rule_name: Annotated[str, Field(description="Rule name.")],
    enabled: Annotated[bool, Field(description="Enable or disable the rule.")],
) -> dict[str, Any]:
    """Enable or disable a rule without deleting it. Wraps EnableTopicRule / DisableTopicRule."""
    try:
        if enabled:
            client.enable_topic_rule(ruleName=rule_name)
        else:
            client.disable_topic_rule(ruleName=rule_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to {'enable' if enabled else 'disable'} topic rule '{rule_name}': {_err(e)}") from e
    return {"ruleName": rule_name, "enabled": enabled}


@mcp.tool()
def delete_topic_rule(
    rule_name: Annotated[str, Field(description="Rule name.")],
    confirm: Annotated[bool, Field(description=_CONFIRM_DESC)] = False,
) -> dict[str, Any]:
    """Delete a rule. Wraps DeleteTopicRule. Irreversible."""
    _require_confirm(confirm, f"delete topic rule '{rule_name}'")
    try:
        client.delete_topic_rule(ruleName=rule_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to delete topic rule '{rule_name}': {_err(e)}") from e
    return {"ruleName": rule_name, "deleted": True}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


@mcp.tool()
def get_endpoint(
    endpoint_type: Annotated[
        Literal["iot:Data-ATS", "iot:Data", "iot:CredentialProvider", "iot:Jobs"],
        Field(description="Which endpoint to look up."),
    ] = "iot:Data-ATS",
) -> dict[str, Any]:
    """Look up this account's IoT Core endpoint. Wraps DescribeEndpoint."""
    try:
        resp = client.describe_endpoint(endpointType=endpoint_type)
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch endpoint: {_err(e)}") from e
    return _strip_response_metadata(resp)


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
