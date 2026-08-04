# IoT MCP Servers

MCP (Model Context Protocol) servers for IoT platforms — giving AI agents full read/write access to device registries, digital twins, and telemetry.

![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
[![CI](https://github.com/nagarjunr/iot-mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/nagarjunr/iot-mcp-servers/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-blueviolet)](https://registry.modelcontextprotocol.io)

## Servers

| Server | Platform | Tools | Package |
|--------|----------|-------|---------|
| [`eclipse-ditto`](eclipse-ditto/) | [Eclipse Ditto](https://eclipse.dev/ditto/) digital twins (open source; also compatible with Bosch IoT Things and other Ditto-based deployments) | 48 | [![PyPI](https://img.shields.io/pypi/v/eclipse-ditto-mcp-server.svg)](https://pypi.org/project/eclipse-ditto-mcp-server/) |
| [`mqtt`](mqtt/) | [MQTT](https://mqtt.org/) 5.0 — the standard IoT pub/sub protocol (any broker: Mosquitto, EMQX, HiveMQ, AWS IoT Core, etc.) | 7 | [![PyPI](https://img.shields.io/pypi/v/mqtt5-mcp-server.svg)](https://pypi.org/project/mqtt5-mcp-server/) |
| [`aws-iot-core`](aws-iot-core/) | [AWS IoT Core](https://aws.amazon.com/iot-core/) — device registry, shadows, jobs, rules, messaging | 48 | [![PyPI](https://img.shields.io/pypi/v/aws-iot-core-mcp-server.svg)](https://pypi.org/project/aws-iot-core-mcp-server/) |
| [`azure-iot-hub`](azure-iot-hub/) | [Azure IoT Hub](https://azure.microsoft.com/en-us/products/iot-hub) — device registry, twins, direct methods, jobs, messaging | 25 | [![PyPI](https://img.shields.io/pypi/v/azure-iot-hub-mcp-server.svg)](https://pypi.org/project/azure-iot-hub-mcp-server/) |
| [`sparkplug-b`](sparkplug-b/) | [Sparkplug B](https://sparkplug.eclipse.org/) — MQTT + protobuf convention for industrial/SCADA data (birth/death, sequenced metrics, commands) | 13 | [![PyPI](https://img.shields.io/pypi/v/sparkplug-b-mcp-server.svg)](https://pypi.org/project/sparkplug-b-mcp-server/) |

Each row links to that server's README for its full tool list, required environment variables, and setup/testing notes.

## Structure

Each server is a standalone directory under this repo — its own `pyproject.toml`, `uv.lock`, `Dockerfile`, and `mcp.json` example config. No shared library layer: every server is independently runnable and dockerizable.

```text
<server-name>/
├── <server-name>mcpserver.py   # FastMCP server (single file)
├── pyproject.toml              # own dependencies
├── uv.lock
├── Dockerfile
├── mcp.json                    # example MCP client config
└── README.md                   # tools, env vars, setup for this server
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management and running servers
- Docker, only if you want to run a server's own test suite against a real/emulated instance (see that server's README)

## Quick start

Install straight from PyPI with [`uv`](https://docs.astral.sh/uv/) or `pipx` — no clone needed:

```bash
uvx eclipse-ditto-mcp-server      # or: mqtt5-mcp-server / aws-iot-core-mcp-server / azure-iot-hub-mcp-server / sparkplug-b-mcp-server
```

Or run from a clone of this repo:

```bash
git clone https://github.com/nagarjunr/iot-mcp-servers.git
cd iot-mcp-servers/<server-name>
uv sync
uv run <server-name>mcpserver.py
```

Each server reads its configuration from environment variables (connection strings, broker host, credentials, etc.) — see that server's README for the full list.

## Using with an MCP client

Each server directory has an `mcp.json` with a ready-to-use client config example (Claude Desktop / VS Code / any MCP client). Copy the relevant block into your client's config, filling in the environment variables described in that server's README. All servers are also listed on the [official MCP registry](https://registry.modelcontextprotocol.io) under `io.github.nagarjunr/<server-name>`.

## Design principles

- **Read-only by default, writes explicit.** Tools default to read/list operations. Any write tool is called out explicitly in that server's README. Create/replace tools default to create-only (`overwrite=False`) — race-free via conditional headers where the target API supports them (e.g. Ditto's `If-None-Match`), otherwise a documented describe-then-create check. Delete tools, where a server needs them, require an explicit `confirm=True` — there is no bulk/cascading delete.
- **No vendor lock-in.** Connectors target the open protocol/API (e.g. Eclipse Ditto's HTTP API, the MQTT wire protocol), not a single vendor's proprietary extension of it, so they work against any compatible deployment. Exception: cloud-provider services like AWS IoT Core are inherently vendor-specific — no lock-in claim applies there, but no cross-vendor abstraction is invented either.
- **Tested against the real thing, with documented exceptions where no free real instance exists.** Each server is verified against a real instance of the target platform (usually via Docker), not hand-rolled mocks. `mqtt` and `sparkplug-b` run against a real Eclipse Mosquitto broker (`sparkplug-b`'s tests simulate the "device" side with the same real protocol library the server uses, so both ends of the wire are genuine). `aws-iot-core` is tested against [moto](https://github.com/getmoto/moto) (AWS IoT Core has no free local emulator; LocalStack's IoT support requires a paid plan). `azure-iot-hub` is tested against [respx](https://github.com/lundberg/respx) for its REST tools; its one AMQP-only tool (`send_c2d_message` — Azure IoT Hub's cloud-to-device send has no REST binding) is tested against a local fake AMQP endpoint built for this repo, since no moto-equivalent exists for Azure and no free Azure IoT Hub emulator exists at all. These are genuine emulators/protocol-level fakes, not naive mocks — see each server's README for specifics and caveats.

## Contributing

Adding a new server? Follow the structure and design principles above, add its row to the `Servers` table, and make sure its test suite runs against a real or faithfully-emulated instance of the target platform (document any exception, as `aws-iot-core` and `azure-iot-hub` do). Issues and PRs welcome.

## License

MIT — see [LICENSE](LICENSE).
