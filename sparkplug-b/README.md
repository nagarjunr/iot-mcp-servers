# Sparkplug B MCP Server

<!-- mcp-name: io.github.nagarjunr/sparkplug-b -->

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for [Sparkplug B](https://sparkplug.eclipse.org/) — the Eclipse-standard MQTT topic/payload convention for industrial/SCADA data (birth/death certificates, sequenced metrics, protobuf payloads). Works against any MQTT broker that carries Sparkplug B traffic; only the open Sparkplug B specification is used, no vendor-specific extensions.

This server acts as a Sparkplug B **Primary Host Application**: it subscribes to the entire `spBv1.0` namespace, discovers Edge Nodes and Devices from their `NBIRTH`/`DBIRTH` messages, tracks their live metrics, and can send them commands (`NCMD`/`DCMD`) — the same role a SCADA/historian host application plays in a real deployment.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and [pysparkplug](https://github.com/matteosox/pysparkplug) (itself built on `paho-mqtt`).

## Tools

| Tool | Description |
|------|-------------|
| `get_connection_status()` | Report the broker connection and this host application's identity. |
| `set_host_online(online)` | Publish this connector's own retained Sparkplug `STATE` message. |
| `list_edge_nodes(group_id?)` | List Edge Nodes discovered via `NBIRTH`/`NDEATH`. |
| `list_devices(group_id?, edge_node_id?)` | List Devices discovered via `DBIRTH`/`DDEATH`. |
| `get_node_metrics(group_id, edge_node_id)` | Latest known metric values for an Edge Node. |
| `get_device_metrics(group_id, edge_node_id, device_id)` | Latest known metric values for a Device. |
| `send_node_command(group_id, edge_node_id, metrics)` | Send an `NCMD` — write one or more of a node's metrics. |
| `send_device_command(group_id, edge_node_id, device_id, metrics)` | Send a `DCMD` — write one or more of a device's metrics. |
| `request_node_rebirth(group_id, edge_node_id)` | Standard `Node Control/Rebirth` command — asks a node to republish its full `NBIRTH`. |
| `start_watch(group_id?, edge_node_id?, device_id?, message_types?)` | Start buffering decoded Sparkplug traffic matching an optional filter. Returns a `session_id`. |
| `get_events(session_id, max_events, timeout_seconds)` | Drain buffered events from a watch session; can wait briefly for one to arrive. |
| `stop_watch(session_id)` | Stop a watch session and discard its buffered events. |
| `list_watches()` | List all active watch sessions. |

### Why watching is session-based

Like the MQTT wire protocol underneath it, Sparkplug B is a continuous stream, not a request/response API — a single MCP tool call can't "wait forever" for the next birth or data message. `start_watch` registers an optional filter (group/node/device/message-type) and buffers matching decoded messages in the background (this connector is always subscribed to the whole `spBv1.0` namespace, so no extra broker subscription is needed per watch); `get_events` drains that buffer, optionally waiting a bounded amount of time for new data. Call `stop_watch` when done.

### Supported metric datatypes

`INT8`/`INT16`/`INT32`/`INT64`, `UINT8`/`UINT16`/`UINT32`/`UINT64`, `FLOAT`, `DOUBLE`, `BOOLEAN`, `STRING`, `TEXT`, `UUID`, `DATETIME`, `BYTES`, `FILE`, and their `*_ARRAY` variants. `DATASET`, `TEMPLATE`, `PROPERTYSET`, and `PROPERTYSETLIST` are part of the Sparkplug B spec but unsupported by the underlying `pysparkplug` codec, so they're rejected with a clear error rather than silently mishandled.

For `send_node_command`/`send_device_command`, `value` shape depends on `datatype`: plain `int`/`float`/`bool`/`str` for scalars, an ISO 8601 string for `DATETIME`, a base64 string for `BYTES`/`FILE`, and a JSON list for `*_ARRAY` types.

## Configuration

| Env var | Required | Description |
|---------|----------|--------------|
| `SPARKPLUG_MQTT_HOST` | Yes | Broker hostname or IP. |
| `SPARKPLUG_HOST_ID` | Yes | This connector's Sparkplug Host Application ID (used in the `spBv1.0/STATE/{id}` topic). |
| `SPARKPLUG_MQTT_PORT` | No | Default `1883`. |
| `SPARKPLUG_MQTT_USERNAME` / `SPARKPLUG_MQTT_PASSWORD` | No | Broker credentials. |
| `SPARKPLUG_MQTT_CLIENT_ID` | No | Defaults to a broker-assigned ID. |
| `SPARKPLUG_MQTT_KEEPALIVE` | No | Seconds, default `60`. |
| `SPARKPLUG_MQTT_CONNECT_TIMEOUT` | No | Seconds to wait for the initial connect, default `10`. |
| `SPARKPLUG_MQTT_USE_TLS` | No | `true`/`false`, default `false`. |
| `SPARKPLUG_MQTT_TLS_CA_CERTS` | No | Path to a CA bundle. Omit to use the system trust store. |
| `SPARKPLUG_MQTT_TLS_CLIENT_CERT` / `SPARKPLUG_MQTT_TLS_CLIENT_KEY` | No | For mutual TLS. |
| `SPARKPLUG_GROUP_ID` | No | Restrict discovery/watching to a single Sparkplug Group ID. Omit to subscribe to every group (`spBv1.0/#`). |

## Running locally

```bash
uv sync
export SPARKPLUG_MQTT_HOST=localhost
export SPARKPLUG_MQTT_PORT=1883
export SPARKPLUG_HOST_ID=my-mcp-host
uv run sparkplugbmcpserver.py
```

See [`mcp.json`](mcp.json) for ready-to-use client configs (stdio and Docker).

## Testing against a real broker

This repo's [design principles](../README.md#design-principles) call for testing against a real instance rather than mocks. `docker-compose.yml` spins up [Eclipse Mosquitto](https://mosquitto.org/) (2.x) with an anonymous listener for local testing. Test fixtures use `pysparkplug`'s own `EdgeNode`/`Device` classes to act as real simulated PLCs/devices — publishing genuine `NBIRTH`/`DBIRTH`/`NDATA`/`DDATA`/`NDEATH` messages and receiving genuine `NCMD`/`DCMD` commands over the wire — so coverage is protocol-level, not hand-rolled mocks. Only the "physical" node/device is simulated, since no free real PLC/edge-node hardware exists to test against; the Sparkplug B protocol handling on both sides is real.

```bash
docker compose up -d       # start Mosquitto on localhost:1883 (anonymous, local testing only)
uv run pytest -v           # tests/conftest.py also starts/stops the stack automatically
docker compose down        # stop it manually if you started it yourself
```

## License notes

`docker-compose.yml` and the files under `docker/` configure the open-source Eclipse Mosquitto broker (EPL-2.0) for local testing only — they are not part of the MCP server itself.
