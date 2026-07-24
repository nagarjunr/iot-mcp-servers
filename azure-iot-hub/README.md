# Azure IoT Hub MCP Server

<!-- mcp-name: io.github.nagarjunr/azure-iot-hub -->

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for [Azure IoT Hub](https://azure.microsoft.com/en-us/products/iot-hub) — device registry, device twins, direct methods, jobs, and messaging.

Scoped to IoT Hub's **service-side data plane** (device management), not [Azure Resource Manager](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/overview). Microsoft's own official [Azure MCP Server](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server) already covers the ARM-level "show me my IoT Hub resource" case — this server covers the actual device-management capability that Azure MCP doesn't.

Calls Azure IoT Hub's REST Service API directly via [httpx](https://www.python-httpx.org/) with a hand-rolled SAS token generator, rather than the official `azure-iot-hub` PyPI package — that package hard-depends on `uamqp`, a C-extension that fails to build on modern Python/platforms (confirmed: it doesn't install on Python 3.12/arm64). Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Tools

### Device registry

| Tool | Description |
|------|-------------|
| `list_devices(max_count)` | List devices. For filtering, prefer `query_devices`. |
| `query_devices(query, max_item_count, continuation_token)` | IoT Hub SQL-like query over devices/twins, with pagination. |
| `get_device(device_id)` | Fetch a device's identity (auth mechanism, status, connection state). |
| `create_device(device_id, auth_type, ..., overwrite=False)` | Register a device. |
| `update_device(device_id, status, status_reason, etag)` | Update a device's enabled/disabled status. |
| `delete_device(device_id, confirm=False, etag)` | Delete a device. **Irreversible.** |

### Modules

| Tool | Description |
|------|-------------|
| `list_modules(device_id)` / `get_module(device_id, module_id)` | List/read module identities on a device. |
| `create_module(device_id, module_id, ..., overwrite=False)` | Register a module. |
| `delete_module(device_id, module_id, confirm=False)` | Delete a module. **Irreversible.** |

### Device & module twins

| Tool | Description |
|------|-------------|
| `get_device_twin(device_id)` / `get_module_twin(device_id, module_id)` | Read a twin (tags, desired/reported properties). |
| `update_device_twin(device_id, tags, desired_properties, etag)` | Merge-update tags/desired properties. |
| `replace_device_twin(device_id, tags, desired_properties, etag)` | Full replace (not merge) of tags/desired properties. |
| `update_module_twin(device_id, module_id, tags, desired_properties, etag)` | Merge-update a module twin. |

### Direct methods

| Tool | Description |
|------|-------------|
| `invoke_device_method(device_id, method_name, payload, ...)` | Invoke a direct method on a device (blocks until the device responds or times out). |
| `invoke_module_method(device_id, module_id, method_name, payload, ...)` | Same, scoped to a module. |

### Jobs (fleet-scale operations)

| Tool | Description |
|------|-------------|
| `create_scheduled_job(job_id, job_type, query_condition, ...)` | Schedule a twin update or direct method across many devices matching a query. |
| `get_scheduled_job(job_id)` / `query_scheduled_jobs(job_type, job_status)` | Read job status/results. |
| `cancel_scheduled_job(job_id, confirm=False)` | Cancel a job. |

### Messaging

| Tool | Description |
|------|-------------|
| `send_c2d_message(device_id, payload, ...)` | Send a cloud-to-device message. **AMQP, not REST** — see caveat below. |
| `purge_c2d_message_queue(device_id)` | Delete all pending C2D messages queued for a device. |

### Statistics

| Tool | Description |
|------|-------------|
| `get_device_statistics()` | Total/enabled/disabled device counts. |
| `get_service_statistics()` | Service-level stats (e.g. connected device count). |

## Important caveat: `send_c2d_message` is AMQP, not REST, and has no real-instance test coverage

Every other tool in this server wraps a documented REST endpoint. Cloud-to-device message **sending** is the one exception: Azure IoT Hub's REST API only exposes the *feedback* side of C2D messaging (delivery receipts); sending is AMQP-protocol-only (confirmed by reading the official `azure-iot-hub` SDK's source — it hands off to an AMQP client, not an HTTP call).

To support it without pulling in the broken `uamqp` dependency, `send_c2d_message` implements the CBS (Claims-Based Security) auth handshake and message send directly against [`python-qpid-proton`](https://github.com/apache/qpid-proton) (the standard AMQP 1.0 library, confirmed to install cleanly on modern Python). The protocol details (CBS field names, `$cbs` node, `/messages/devicebound` target address, `to` property format) were confirmed from Microsoft's own pure-Python AMQP implementation in `azure-eventhub`/`azure-servicebus`, not guessed.

**This tool is not covered by real-instance testing.** There's no free Azure IoT Hub emulator (see Testing below), and the test suite's `respx` HTTP mocking can't exercise AMQP at all. Tests instead run this against a **local fake AMQP endpoint** (also built with `qpid-proton`) that implements just enough of the CBS handshake and `/messages/devicebound` receiver to prove the wire protocol is well-formed — it does not validate genuine Azure IoT Hub business logic. **Verify against a real hub before relying on this in production.**

## Safety conventions

Same as the rest of this repo: `create_*` defaults to `overwrite=False` (best-effort describe-then-create check — IoT Hub's `If-Match` header is for optimistic-concurrency on updates, not create-only semantics, so this isn't fully race-free like Ditto's `If-None-Match`). Every `delete_*`/`cancel_*` requires `confirm=True`.

## Configuration

| Env var | Required | Description |
|---------|----------|--------------|
| `AZURE_IOT_HUB_CONNECTION_STRING` | Yes | An IoT Hub connection string with `service` (or `iothubowner`) rights, e.g. `HostName=my-hub.azure-devices.net;SharedAccessKeyName=service;SharedAccessKey=...`. Find this under your hub's "Shared access policies" in the Azure portal. |
| `AZURE_IOT_HUB_AMQP_PORT` | No | Default `5671`. Only relevant to `send_c2d_message`. |
| `AZURE_IOT_HUB_AMQP_USE_TLS` | No | `true`/`false`, default `true`. Set `false` only for local/test endpoints. |
| `AZURE_IOT_HUB_AMQP_HOSTNAME_OVERRIDE` | No | Override the AMQP connection target (e.g. a local test fixture) without changing the REST hostname derived from the connection string. |

## Running locally

```bash
uv sync
export AZURE_IOT_HUB_CONNECTION_STRING="HostName=my-hub.azure-devices.net;SharedAccessKeyName=service;SharedAccessKey=..."
uv run azureiothubmcpserver.py
```

See [`mcp.json`](mcp.json) for ready-to-use client configs (stdio and Docker).

## Testing

This repo's [design principles](../README.md#design-principles) call for testing against a real instance rather than mocks. Azure IoT Hub has no official local emulator and no `moto`-equivalent exists for it. REST endpoints are tested with [respx](https://github.com/lundberg/respx) (httpx's dedicated mocking library, using realistic Azure response shapes); `send_c2d_message` is tested against a local fake AMQP endpoint (see caveat above).

```bash
uv run pytest -v
```

## License notes

No bundled deployment artifacts here (unlike `eclipse-ditto`/`mqtt`) since there's no local broker/service to run — Azure IoT Hub only exists as an Azure-hosted service.
