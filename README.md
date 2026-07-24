# IoT MCP Servers

MCP (Model Context Protocol) servers for IoT platforms — giving AI agents read access to device registries, digital twins, and telemetry.

![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

## Structure

Each server is a standalone directory under this repo — its own `pyproject.toml`, `uv.lock`, `Dockerfile`, and `mcp.json` example config. No shared library layer: every server is independently runnable and dockerizable.

```
<server-name>/
├── <server-name>mcpserver.py   # FastMCP server (single file)
├── pyproject.toml              # own dependencies
├── uv.lock
├── Dockerfile
├── mcp.json                    # example MCP client config
└── README.md                   # tools, env vars, setup for this server
```

## Servers

| Server | Platform | Status |
|--------|----------|--------|
| [`eclipse-ditto`](eclipse-ditto/) | [Eclipse Ditto](https://eclipse.dev/ditto/) digital twins (open source; also compatible with Bosch IoT Things and other Ditto-based deployments) | ✅ |
| [`mqtt`](mqtt/) | [MQTT](https://mqtt.org/) 5.0 — the standard IoT pub/sub protocol (any broker: Mosquitto, EMQX, HiveMQ, AWS IoT Core, etc.) | ✅ |

More planned: Azure IoT Hub.

## Running a server locally

```bash
cd <server-name>
uv sync
uv run <server-name>mcpserver.py
```

## Using with an MCP client

Each server directory has an `mcp.json` with a ready-to-use client config example (Claude Desktop / VS Code / any MCP client). Copy the relevant block into your client's config, filling in the environment variables described in that server's README.

## Design principles

- **Read-only by default, writes explicit.** Tools default to read/list operations. Any write tool is called out explicitly in that server's README. Create/replace tools default to create-only (`overwrite=False`) using conditional HTTP headers rather than check-then-set, so the safe path is race-free, not just the default. Delete tools, where a server needs them, require an explicit `confirm=True` — there is no bulk/cascading delete.
- **No vendor lock-in.** Connectors target the open protocol/API (e.g. Eclipse Ditto's HTTP API), not a single vendor's proprietary extension of it, so they work against any compatible deployment.
- **Tested against the real thing.** Each server is verified against a real instance of the target platform (usually via Docker), not just mocks.

## License

MIT — see [LICENSE](LICENSE).
