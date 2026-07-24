# MQTT MCP Server

<!-- mcp-name: io.github.nagarjunr/mqtt -->

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for [MQTT](https://mqtt.org/) — the standard IoT publish/subscribe messaging protocol. Works against any MQTT broker (Eclipse Mosquitto, EMQX, HiveMQ, AWS IoT Core, Azure IoT Hub's MQTT endpoint, etc): only the standard MQTT 5.0 wire protocol is used, no broker-specific admin APIs.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and [paho-mqtt](https://eclipse.dev/paho/).

## Tools

| Tool | Description |
|------|-------------|
| `get_connection_status()` | Report this connector's broker connection state. |
| `publish_message(topic, payload, qos, retain, ...)` | Publish a message. Supports MQTT5 properties (content type, message expiry, response topic, correlation data, user properties) and optionally blocks until the broker acknowledges delivery (QoS 1/2). |
| `start_subscription(topic_filter, qos, ...)` | Start receiving messages matching a topic filter (supports `+`/`#` wildcards). Returns a `session_id`. |
| `get_messages(session_id, max_messages, timeout_seconds)` | Drain buffered messages from a subscription session; can wait briefly for one to arrive. |
| `stop_subscription(session_id)` | Stop a session and unsubscribe (if no other session needs the same filter). |
| `list_subscriptions()` | List all active subscription sessions. |
| `discover_topics(topic_filter, duration_seconds, max_topics)` | Approximate a "list topics" operation via retained messages — MQTT has no native topic-listing operation. |

### Why subscriptions are session-based

MQTT is a continuous publish/subscribe stream, not a request/response API. A single MCP tool call can't "wait forever" for messages, so subscribing works in two steps: `start_subscription` registers interest and buffers messages in the background (one shared broker connection, dispatched in-process by topic filter), then `get_messages` drains that buffer on however many tool calls you want, optionally waiting a bounded amount of time for new data. Call `stop_subscription` when done.

## Configuration

| Env var | Required | Description |
|---------|----------|--------------|
| `MQTT_HOST` | Yes | Broker hostname or IP. |
| `MQTT_PORT` | No | Default `1883` (or `8883` for TLS — set explicitly). |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | No | Broker credentials. |
| `MQTT_CLIENT_ID` | No | Defaults to a broker-assigned ID. |
| `MQTT_KEEPALIVE` | No | Seconds, default `60`. |
| `MQTT_CONNECT_TIMEOUT` | No | Seconds to wait for the initial connect, default `10`. |
| `MQTT_TRANSPORT` | No | `tcp` (default) or `websockets`. |
| `MQTT_WS_PATH` | No | Path for the websocket transport, default `/mqtt`. |
| `MQTT_USE_TLS` | No | `true`/`false`, default `false`. |
| `MQTT_TLS_CA_CERTS` | No | Path to a CA bundle. Omit to use the system trust store. |
| `MQTT_TLS_CLIENT_CERT` / `MQTT_TLS_CLIENT_KEY` | No | For mutual TLS. |
| `MQTT_TLS_INSECURE` | No | Skip hostname verification — for self-signed test certs only. |
| `MQTT_WILL_TOPIC` / `MQTT_WILL_PAYLOAD` / `MQTT_WILL_QOS` / `MQTT_WILL_RETAIN` | No | Last Will and Testament, set once at connect time. |

## Running locally

```bash
uv sync
export MQTT_HOST=localhost
export MQTT_PORT=1883
export MQTT_USERNAME=mqtt
export MQTT_PASSWORD=mqtt
uv run mqttmcpserver.py
```

See [`mcp.json`](mcp.json) for ready-to-use client configs (stdio and Docker).

## Testing against a real broker

This repo's [design principles](../README.md#design-principles) call for testing against a real instance rather than mocks. `docker-compose.yml` spins up [Eclipse Mosquitto](https://mosquitto.org/) (2.x, MQTT5-capable) with password auth, plus a TLS listener with self-signed certs for testing the TLS/mTLS code paths.

```bash
docker compose up -d       # start Mosquitto on localhost:1883 (plain, user: mqtt / pass: mqtt) and :8883 (TLS)
uv run pytest -v           # tests/conftest.py also starts/stops the stack automatically
docker compose down        # stop it manually if you started it yourself
```

## License notes

`docker-compose.yml` and the files under `docker/` configure the open-source Eclipse Mosquitto broker (EPL-2.0) for local testing only — they are not part of the MCP server itself.
