# AWS IoT Core MCP Server

<!-- mcp-name: io.github.nagarjunr/aws-iot-core -->

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for [AWS IoT Core](https://aws.amazon.com/iot-core/) — device registry, device shadows, jobs (fleet management), the rules engine, and messaging.

Scoped deliberately to IoT Core itself: no [Greengrass](https://aws.amazon.com/greengrass/) (separate edge-deployment API), no [IoT SiteWise](https://aws.amazon.com/iot-sitewise/) (already has an official [awslabs MCP server](https://github.com/awslabs/mcp/tree/main/src/aws-iot-sitewise-mcp-server)), no Device Defender/Events/TwinMaker — each of those is its own AWS service with its own API and would be its own connector.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and [boto3](https://boto3.amazonaws.com/).

## Tools

### Things (device registry)

| Tool | Description |
|------|-------------|
| `list_things(thing_type_name, attribute_name, attribute_value, thing_group_name, max_results)` | List things, optionally filtered. |
| `search_things(query_string, index_name, max_results)` | Fleet-indexing search, e.g. `attributes.location:"lab-1"`. Requires indexing to be enabled. |
| `get_thing(thing_name)` | Fetch a thing's attributes and type. |
| `create_thing(thing_name, thing_type_name, attributes, billing_group_name, overwrite=False)` | Register a new thing. |
| `update_thing(thing_name, attributes, thing_type_name, remove_thing_type, attributes_merge=True)` | Update a thing's attributes/type. |
| `delete_thing(thing_name, confirm=False)` | Delete a thing. **Irreversible.** |

### Thing Types & Thing Groups

| Tool | Description |
|------|-------------|
| `list_thing_types(thing_type_name)` / `get_thing_type(thing_type_name)` | List/read thing types. |
| `create_thing_type(thing_type_name, description, searchable_attributes)` | Create a thing type. Immutable once created (AWS limitation) — only deprecation is supported after. |
| `deprecate_thing_type(thing_type_name, undo=False)` | Deprecate (or un-deprecate) a thing type. |
| `list_thing_groups(parent_group, name_prefix_filter)` / `get_thing_group(thing_group_name)` | List/read thing groups. |
| `create_thing_group(thing_group_name, parent_group_name, attributes, overwrite=False)` | Create a thing group. |
| `delete_thing_group(thing_group_name, confirm=False)` | Delete a thing group. **Irreversible.** |
| `modify_thing_group_membership(thing_name, thing_group_name, action)` | `action="add"` or `"remove"` a thing from a group. |
| `list_things_in_thing_group(thing_group_name)` | List members of a group. |

### Device Shadows (data plane)

| Tool | Description |
|------|-------------|
| `get_thing_shadow(thing_name, shadow_name)` | Read a thing's shadow document (`desired`/`reported`/`delta`). Omit `shadow_name` for the classic (unnamed) shadow. |
| `update_thing_shadow(thing_name, desired, reported, shadow_name)` | Merge-update `desired` and/or `reported` state. |
| `delete_thing_shadow(thing_name, shadow_name, confirm=False)` | Delete a shadow document. |
| `list_named_shadows_for_thing(thing_name)` | List named (non-classic) shadows for a thing. |

### Messaging

| Tool | Description |
|------|-------------|
| `publish_message(topic, payload, qos=0)` | Publish an MQTT message to the device fleet via the IoT Data Plane. |

### Jobs (fleet management)

| Tool | Description |
|------|-------------|
| `list_jobs(status, thing_group_name, max_results)` / `get_job(job_id)` | List/read jobs. |
| `create_job(job_id, thing_arns, document, description, target_selection="SNAPSHOT")` | Create a fleet job (e.g. an OTA update or remote command). |
| `cancel_job(job_id, confirm=False, comment, force=False)` | Cancel a job. |
| `delete_job(job_id, confirm=False, force=False)` | Delete a job. **Irreversible.** |
| `list_job_executions_for_job(job_id, status)` / `list_job_executions_for_thing(thing_name, status)` | Track per-device execution status. |

### Certificates & Policies (device auth)

| Tool | Description |
|------|-------------|
| `create_keys_and_certificate(set_as_active=True)` | Generate a new key pair + certificate. **The private key is returned only once** — capture it immediately. |
| `get_certificate(certificate_id)` / `list_certificates(page_size)` | Read certificate metadata. |
| `set_certificate_status(certificate_id, status)` | `ACTIVE`, `INACTIVE`, or `REVOKED`. |
| `delete_certificate(certificate_id, confirm=False, force_delete=False)` | Delete a certificate. **Irreversible.** |
| `create_policy(policy_name, policy_document, overwrite=False)` / `get_policy` / `list_policies` | Manage IAM-style IoT policies (JSON documents). |
| `delete_policy(policy_name, confirm=False)` | Delete a policy. **Irreversible.** |
| `modify_policy_attachment(policy_name, target, action)` | Attach/detach a policy to/from a certificate ARN. |
| `modify_thing_principal(thing_name, principal, action)` | Attach/detach a certificate (principal) to/from a thing. |
| `list_thing_principals(thing_name)` / `list_principal_things(principal)` | Look up thing↔certificate associations either direction. |

### Rules Engine

| Tool | Description |
|------|-------------|
| `list_topic_rules(topic)` / `get_topic_rule(rule_name)` | List/read SQL-based message routing rules. |
| `put_topic_rule(rule_name, sql, actions, description, sql_version, overwrite=False)` | Create or replace a rule. `actions` is a list of raw AWS action objects (e.g. `{"lambda": {"functionArn": "..."}}`). |
| `set_topic_rule_enabled(rule_name, enabled)` | Enable/disable a rule without deleting it. |
| `delete_topic_rule(rule_name, confirm=False)` | Delete a rule. **Irreversible.** |

### Misc

| Tool | Description |
|------|-------------|
| `get_endpoint(endpoint_type)` | Look up this account's IoT Core data endpoint (default `iot:Data-ATS`). |

## Safety conventions

Same as the rest of this repo: `create_*`/`put_*` default to `overwrite=False` (best-effort — the AWS IoT API itself has no conditional-write header for most of these operations, so this is a describe-then-create check, not fully race-free like Ditto's `If-None-Match`). Every `delete_*`/`cancel_*` requires `confirm=True`.

## Configuration

Standard AWS SDK credential resolution — no custom env vars for auth. Set whichever of these your setup uses:

| Env var | Description |
|---------|-------------|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` | Explicit credentials. |
| `AWS_PROFILE` | Named profile from `~/.aws/credentials`. |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | Required — AWS IoT Core is regional. |
| `AWS_ENDPOINT_URL` | Override the API endpoint (e.g. for LocalStack). boto3 reads this natively. |

Or an IAM role, if running somewhere with one attached (EC2/ECS/Lambda). See [boto3's credential docs](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html).

## Running locally

```bash
uv sync
export AWS_REGION=us-east-1
# plus whichever credential env vars apply to you
uv run awsiotcoremcpserver.py
```

See [`mcp.json`](mcp.json) for ready-to-use client configs (stdio and Docker).

## Testing

This repo's [design principles](../README.md#design-principles) call for testing against a real instance rather than mocks. AWS IoT Core has no official local emulator, and [LocalStack's IoT support requires a paid plan](https://docs.localstack.cloud/aws/services/iot/) (no free tier) — so this server is the one exception in this repo: tests run against [moto](https://github.com/getmoto/moto), a mature, free, open-source AWS API emulator (not hand-rolled mocks — it implements real request/response behavior for the actual boto3 calls this server makes).

```bash
uv run pytest -v
```

## License notes

No bundled deployment artifacts here (unlike the other servers) since there's no local broker/service to run — AWS IoT Core only exists as an AWS-hosted service.
