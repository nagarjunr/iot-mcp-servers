import base64
import collections
import dataclasses
import datetime
import logging
import os
import threading
import time
import uuid
from typing import Annotated, Any, Literal

import pysparkplug as spb
from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

MQTT_HOST = os.environ["SPARKPLUG_MQTT_HOST"]
MQTT_PORT = int(os.getenv("SPARKPLUG_MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("SPARKPLUG_MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("SPARKPLUG_MQTT_PASSWORD")
MQTT_CLIENT_ID = os.getenv("SPARKPLUG_MQTT_CLIENT_ID") or None
MQTT_KEEPALIVE = int(os.getenv("SPARKPLUG_MQTT_KEEPALIVE", "60"))
MQTT_CONNECT_TIMEOUT = float(os.getenv("SPARKPLUG_MQTT_CONNECT_TIMEOUT", "10.0"))

MQTT_USE_TLS = os.getenv("SPARKPLUG_MQTT_USE_TLS", "false").lower() == "true"
MQTT_TLS_CA_CERTS = os.getenv("SPARKPLUG_MQTT_TLS_CA_CERTS")
MQTT_TLS_CLIENT_CERT = os.getenv("SPARKPLUG_MQTT_TLS_CLIENT_CERT")
MQTT_TLS_CLIENT_KEY = os.getenv("SPARKPLUG_MQTT_TLS_CLIENT_KEY")

HOST_ID = os.environ["SPARKPLUG_HOST_ID"]
GROUP_ID_FILTER = os.getenv("SPARKPLUG_GROUP_ID") or None

_SUPPORTED_DATATYPES = sorted(
    d.name
    for d in spb.DataType
    if d.name not in {"UNKNOWN", "DATASET", "TEMPLATE", "PROPERTYSET", "PROPERTYSETLIST"}
)
_METRICS_DESC = (
    "Metrics to send, each {'name': str, 'value': ..., 'datatype': one of "
    + ", ".join(_SUPPORTED_DATATYPES)
    + "}. 'value' shape depends on datatype: ISO 8601 string for DATETIME, "
    "base64 string for BYTES/FILE, a JSON list for *_ARRAY types, plain "
    "int/float/bool/str otherwise."
)
_SESSION_ID_DESC = "Session ID returned by start_watch."
_MESSAGE_TYPES = sorted(m.value for m in spb.MessageType)
_MESSAGE_TYPE_DESC = f"Sparkplug message types to include, e.g. {_MESSAGE_TYPES}. Omit for all types."


# ---------------------------------------------------------------------------
# Discovered node/device state
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _NodeState:
    group_id: str
    edge_node_id: str
    online: bool = False
    seq: int | None = None
    last_birth_ts: float | None = None
    last_death_ts: float | None = None
    last_seen_ts: float | None = None
    metrics: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class _DeviceState:
    group_id: str
    edge_node_id: str
    device_id: str
    online: bool = False
    seq: int | None = None
    last_birth_ts: float | None = None
    last_death_ts: float | None = None
    last_seen_ts: float | None = None
    metrics: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)


_nodes: dict[tuple[str, str], _NodeState] = {}
_devices: dict[tuple[str, str, str], _DeviceState] = {}
_state_lock = threading.Lock()


def _get_node(group_id: str, edge_node_id: str) -> _NodeState:
    key = (group_id, edge_node_id)
    node = _nodes.get(key)
    if node is None:
        node = _NodeState(group_id=group_id, edge_node_id=edge_node_id)
        _nodes[key] = node
    return node


def _get_device(group_id: str, edge_node_id: str, device_id: str) -> _DeviceState:
    key = (group_id, edge_node_id, device_id)
    device = _devices.get(key)
    if device is None:
        device = _DeviceState(group_id=group_id, edge_node_id=edge_node_id, device_id=device_id)
        _devices[key] = device
    return device


# ---------------------------------------------------------------------------
# Watch sessions (buffered decoded Sparkplug traffic, mirrors mqtt/'s subscription sessions)
# ---------------------------------------------------------------------------


class _WatchSession:
    def __init__(
        self,
        session_id: str,
        group_id: str | None,
        edge_node_id: str | None,
        device_id: str | None,
        message_types: set[str] | None,
    ):
        self.session_id = session_id
        self.group_id = group_id
        self.edge_node_id = edge_node_id
        self.device_id = device_id
        self.message_types = message_types
        self.buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=10000)
        self.lock = threading.Lock()
        self.new_event = threading.Event()
        self.created_at = time.time()
        self.event_count = 0


_watch_sessions: dict[str, _WatchSession] = {}
_watch_sessions_lock = threading.Lock()


def _dispatch_event(
    event: dict[str, Any],
    *,
    group_id: str | None,
    edge_node_id: str | None,
    device_id: str | None,
    message_type: str | None,
) -> None:
    with _watch_sessions_lock:
        sessions = list(_watch_sessions.values())
    for session in sessions:
        if session.group_id is not None and session.group_id != group_id:
            continue
        if session.edge_node_id is not None and session.edge_node_id != edge_node_id:
            continue
        if session.device_id is not None and session.device_id != device_id:
            continue
        if session.message_types is not None and message_type not in session.message_types:
            continue
        with session.lock:
            session.buffer.append(event)
            session.event_count += 1
        session.new_event.set()


# ---------------------------------------------------------------------------
# Metric (de)serialization
# ---------------------------------------------------------------------------


def _serialize_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


def _serialize_metric(metric: "spb.Metric") -> dict[str, Any]:
    value: Any = metric.value
    if isinstance(value, tuple):
        value = [_serialize_scalar(v) for v in value]
    else:
        value = _serialize_scalar(value)
    return {
        "name": metric.name,
        "value": value,
        "datatype": metric.datatype.name,
        "timestamp": metric.timestamp,
        "alias": metric.alias,
        "is_historical": metric.is_historical,
        "is_transient": metric.is_transient,
        "is_null": metric.is_null,
    }


def _coerce_metric_value(datatype: "spb.DataType", raw_value: Any) -> Any:
    if raw_value is None:
        return None
    if datatype == spb.DataType.DATETIME:
        return datetime.datetime.fromisoformat(raw_value) if isinstance(raw_value, str) else raw_value
    if datatype in (spb.DataType.BYTES, spb.DataType.FILE):
        return base64.b64decode(raw_value) if isinstance(raw_value, str) else raw_value
    if datatype == spb.DataType.DATETIME_ARRAY:
        return tuple(datetime.datetime.fromisoformat(v) if isinstance(v, str) else v for v in raw_value)
    if datatype.name.endswith("_ARRAY"):
        return tuple(raw_value)
    return raw_value


def _build_metric(spec: dict[str, Any]) -> "spb.Metric":
    name = spec["name"]
    datatype_name = str(spec["datatype"]).upper()
    if datatype_name not in _SUPPORTED_DATATYPES:
        raise ValueError(f"Unsupported or invalid Sparkplug datatype '{spec['datatype']}'. Supported: {_SUPPORTED_DATATYPES}")
    datatype = spb.DataType[datatype_name]
    value = _coerce_metric_value(datatype, spec.get("value"))
    return spb.Metric(timestamp=spb.get_current_timestamp(), name=name, datatype=datatype, value=value)


# ---------------------------------------------------------------------------
# Incoming Sparkplug message handling
# ---------------------------------------------------------------------------


def _handle_spb_message(message: "spb.Message") -> None:
    topic = message.topic
    payload = message.payload

    if topic.message_type == spb.MessageType.STATE:
        assert isinstance(payload, spb.State)
        state_event: dict[str, Any] = {
            "message_type": "STATE",
            "sparkplug_host_id": topic.sparkplug_host_id,
            "online": payload.online,
            "timestamp": payload.timestamp,
        }
        _dispatch_event(state_event, group_id=None, edge_node_id=None, device_id=None, message_type="STATE")
        return

    mtype = topic.message_type
    assert isinstance(mtype, spb.MessageType)
    group_id = topic.group_id
    edge_node_id = topic.edge_node_id
    device_id = topic.device_id
    assert group_id is not None and edge_node_id is not None
    now = time.time()

    event: dict[str, Any] = {
        "message_type": mtype.value,
        "group_id": group_id,
        "edge_node_id": edge_node_id,
        "device_id": device_id,
        "timestamp": getattr(payload, "timestamp", None),
    }
    metrics = getattr(payload, "metrics", None)
    if metrics is not None:
        event["metrics"] = [_serialize_metric(m) for m in metrics]

    with _state_lock:
        if mtype in (spb.MessageType.NBIRTH, spb.MessageType.NDATA):
            node = _get_node(group_id, edge_node_id)
            node.online = True
            node.last_seen_ts = now
            node.seq = getattr(payload, "seq", None)
            if mtype is spb.MessageType.NBIRTH:
                node.last_birth_ts = now
                node.metrics.clear()
            for m in metrics or ():
                if m.name:
                    node.metrics[m.name] = _serialize_metric(m)
        elif mtype is spb.MessageType.NDEATH:
            node = _get_node(group_id, edge_node_id)
            node.online = False
            node.last_death_ts = now
            for device in _devices.values():
                if device.group_id == group_id and device.edge_node_id == edge_node_id:
                    device.online = False
                    device.last_death_ts = now
        elif mtype in (spb.MessageType.DBIRTH, spb.MessageType.DDATA):
            assert device_id is not None
            device = _get_device(group_id, edge_node_id, device_id)
            device.online = True
            device.last_seen_ts = now
            device.seq = getattr(payload, "seq", None)
            if mtype is spb.MessageType.DBIRTH:
                device.last_birth_ts = now
                device.metrics.clear()
            for m in metrics or ():
                if m.name:
                    device.metrics[m.name] = _serialize_metric(m)
        elif mtype is spb.MessageType.DDEATH:
            assert device_id is not None
            device = _get_device(group_id, edge_node_id, device_id)
            device.online = False
            device.last_death_ts = now
        # NCMD/DCMD: no state to update, just surfaced via the event buffer below.

    _dispatch_event(
        event,
        group_id=group_id,
        edge_node_id=edge_node_id,
        device_id=device_id,
        message_type=mtype.value,
    )


# ---------------------------------------------------------------------------
# Connection setup
# ---------------------------------------------------------------------------


def _state_topic() -> "spb.Topic":
    return spb.Topic(message_type=spb.MessageType.STATE, sparkplug_host_id=HOST_ID)


def _publish_host_state(online: bool) -> None:
    payload = spb.State(timestamp=spb.get_current_timestamp(), online=online)
    message = spb.Message(topic=_state_topic(), payload=payload, qos=spb.QoS.AT_LEAST_ONCE, retain=True)
    client.publish(message)


_connect_event = threading.Event()


def _on_client_connect(_client: "spb.Client") -> None:
    _connect_event.set()


def _build_client() -> "spb.Client":
    transport_config = None
    if MQTT_USE_TLS:
        transport_config = spb.TLSConfig(
            ca_certs=MQTT_TLS_CA_CERTS,
            certfile=MQTT_TLS_CLIENT_CERT,
            keyfile=MQTT_TLS_CLIENT_KEY,
        )

    clnt = spb.Client(
        client_id=MQTT_CLIENT_ID,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
        transport_config=transport_config,
    )

    watch_topic = spb.Topic(group_id=GROUP_ID_FILTER if GROUP_ID_FILTER else spb.MULTI_LEVEL_WILDCARD)
    clnt.subscribe(
        topic=watch_topic,
        qos=spb.QoS.AT_LEAST_ONCE,
        callback=lambda _c, message: _handle_spb_message(message),
    )

    offline_state = spb.State(timestamp=spb.get_current_timestamp(), online=False)
    clnt.set_will(spb.Message(topic=_state_topic(), payload=offline_state, qos=spb.QoS.AT_LEAST_ONCE, retain=True))

    clnt.connect(
        MQTT_HOST,
        port=MQTT_PORT,
        keepalive=MQTT_KEEPALIVE,
        blocking=False,
        callback=_on_client_connect,
    )

    if not _connect_event.wait(timeout=MQTT_CONNECT_TIMEOUT):
        clnt.disconnect()
        raise RuntimeError(
            f"Timed out connecting to MQTT broker {MQTT_HOST}:{MQTT_PORT} after {MQTT_CONNECT_TIMEOUT}s "
            "(check host/port/credentials; a rejected CONNACK is logged by the underlying client "
            "but not raised synchronously here)"
        )
    return clnt


client = _build_client()
_publish_host_state(True)

mcp = FastMCP("sparkplug-b")


# ---------------------------------------------------------------------------
# Connection & host status
# ---------------------------------------------------------------------------


@mcp.tool()
def get_connection_status() -> dict[str, Any]:
    """Report this connector's connection to the MQTT broker and its Sparkplug Host Application identity.

    This server acts as a Sparkplug B Primary Host Application: it subscribes to the
    entire spBv1.0 namespace, discovers Edge Nodes/Devices from their BIRTH messages,
    and can issue commands to them.

    Returns:
        {connected, host, port, sparkplug_host_id, group_id_filter, known_edge_nodes, known_devices}
    """
    with _state_lock:
        node_count = len(_nodes)
        device_count = len(_devices)
    return {
        "connected": client._client.is_connected(),
        "host": MQTT_HOST,
        "port": MQTT_PORT,
        "sparkplug_host_id": HOST_ID,
        "group_id_filter": GROUP_ID_FILTER,
        "known_edge_nodes": node_count,
        "known_devices": device_count,
    }


@mcp.tool()
def set_host_online(
    online: Annotated[bool, Field(description="True to publish this Primary Host Application as ONLINE, False as OFFLINE.")],
) -> dict[str, Any]:
    """Publish this connector's own Sparkplug Host Application STATE message.

    Retained on spBv1.0/STATE/{sparkplug_host_id} per spec, so Edge Nodes and
    other Host Applications can tell whether this host is actively monitoring
    the infrastructure. Published automatically as online=True at startup,
    with an MQTT will registered to publish online=False if the connection
    drops unexpectedly. Use this tool for explicit control, e.g. announcing a
    planned maintenance window.
    """
    _publish_host_state(online)
    return {"sparkplug_host_id": HOST_ID, "online": online}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@mcp.tool()
def list_edge_nodes(
    group_id: Annotated[str | None, Field(description="Restrict to this Sparkplug Group ID; omit to list all groups.")] = None,
) -> dict[str, Any]:
    """List Sparkplug Edge Nodes discovered via NBIRTH/NDEATH messages since this connector started.

    Returns:
        {edge_nodes: [{group_id, edge_node_id, online, seq, last_birth_timestamp, last_death_timestamp, last_seen_timestamp, metric_count}], count}
    """
    with _state_lock:
        nodes = [n for n in _nodes.values() if group_id is None or n.group_id == group_id]
        result = [
            {
                "group_id": n.group_id,
                "edge_node_id": n.edge_node_id,
                "online": n.online,
                "seq": n.seq,
                "last_birth_timestamp": n.last_birth_ts,
                "last_death_timestamp": n.last_death_ts,
                "last_seen_timestamp": n.last_seen_ts,
                "metric_count": len(n.metrics),
            }
            for n in nodes
        ]
    return {"edge_nodes": result, "count": len(result)}


@mcp.tool()
def list_devices(
    group_id: Annotated[str | None, Field(description="Restrict to this Sparkplug Group ID; omit for all groups.")] = None,
    edge_node_id: Annotated[str | None, Field(description="Restrict to this Edge Node ID; omit for all nodes.")] = None,
) -> dict[str, Any]:
    """List Sparkplug Devices discovered via DBIRTH/DDEATH messages since this connector started.

    Returns:
        {devices: [{group_id, edge_node_id, device_id, online, seq, last_birth_timestamp, last_death_timestamp, last_seen_timestamp, metric_count}], count}
    """
    with _state_lock:
        devices = [
            d
            for d in _devices.values()
            if (group_id is None or d.group_id == group_id) and (edge_node_id is None or d.edge_node_id == edge_node_id)
        ]
        result = [
            {
                "group_id": d.group_id,
                "edge_node_id": d.edge_node_id,
                "device_id": d.device_id,
                "online": d.online,
                "seq": d.seq,
                "last_birth_timestamp": d.last_birth_ts,
                "last_death_timestamp": d.last_death_ts,
                "last_seen_timestamp": d.last_seen_ts,
                "metric_count": len(d.metrics),
            }
            for d in devices
        ]
    return {"devices": result, "count": len(result)}


@mcp.tool()
def get_node_metrics(
    group_id: Annotated[str, Field(description="Sparkplug Group ID.")],
    edge_node_id: Annotated[str, Field(description="Sparkplug Edge Node ID.")],
) -> dict[str, Any]:
    """Get the latest known metric values for an Edge Node (from its NBIRTH/NDATA messages).

    Returns:
        {group_id, edge_node_id, online, metrics: {name: {value, datatype, timestamp, alias, is_historical, is_transient, is_null}}}
    """
    with _state_lock:
        node = _nodes.get((group_id, edge_node_id))
        if node is None:
            raise ValueError(f"Unknown edge node: group_id='{group_id}', edge_node_id='{edge_node_id}'")
        return {
            "group_id": node.group_id,
            "edge_node_id": node.edge_node_id,
            "online": node.online,
            "metrics": dict(node.metrics),
        }


@mcp.tool()
def get_device_metrics(
    group_id: Annotated[str, Field(description="Sparkplug Group ID.")],
    edge_node_id: Annotated[str, Field(description="Sparkplug Edge Node ID.")],
    device_id: Annotated[str, Field(description="Sparkplug Device ID.")],
) -> dict[str, Any]:
    """Get the latest known metric values for a Device (from its DBIRTH/DDATA messages).

    Returns:
        {group_id, edge_node_id, device_id, online, metrics: {name: {value, datatype, timestamp, alias, is_historical, is_transient, is_null}}}
    """
    with _state_lock:
        device = _devices.get((group_id, edge_node_id, device_id))
        if device is None:
            raise ValueError(f"Unknown device: group_id='{group_id}', edge_node_id='{edge_node_id}', device_id='{device_id}'")
        return {
            "group_id": device.group_id,
            "edge_node_id": device.edge_node_id,
            "device_id": device.device_id,
            "online": device.online,
            "metrics": dict(device.metrics),
        }


# ---------------------------------------------------------------------------
# Commands (writes)
# ---------------------------------------------------------------------------


@mcp.tool()
def send_node_command(
    group_id: Annotated[str, Field(description="Sparkplug Group ID.")],
    edge_node_id: Annotated[str, Field(description="Sparkplug Edge Node ID.")],
    metrics: Annotated[list[dict[str, Any]], Field(description=_METRICS_DESC)],
) -> dict[str, Any]:
    """Send an NCMD to a Sparkplug Edge Node to write one or more of its metrics.

    Used for writes like setpoints or mode changes. The edge node's own
    application logic decides how to act on the command; this only publishes it.

    Returns:
        {group_id, edge_node_id, metrics_sent}
    """
    built = [_build_metric(m) for m in metrics]
    payload = spb.NCmd(timestamp=spb.get_current_timestamp(), metrics=tuple(built))
    topic = spb.Topic(message_type=spb.MessageType.NCMD, group_id=group_id, edge_node_id=edge_node_id)
    message = spb.Message(topic=topic, payload=payload, qos=spb.QoS.AT_LEAST_ONCE, retain=False)
    client.publish(message, include_dtypes=True)
    return {"group_id": group_id, "edge_node_id": edge_node_id, "metrics_sent": [m.name for m in built]}


@mcp.tool()
def send_device_command(
    group_id: Annotated[str, Field(description="Sparkplug Group ID.")],
    edge_node_id: Annotated[str, Field(description="Sparkplug Edge Node ID.")],
    device_id: Annotated[str, Field(description="Sparkplug Device ID.")],
    metrics: Annotated[list[dict[str, Any]], Field(description=_METRICS_DESC)],
) -> dict[str, Any]:
    """Send a DCMD to a Sparkplug Device to write one or more of its metrics.

    Returns:
        {group_id, edge_node_id, device_id, metrics_sent}
    """
    built = [_build_metric(m) for m in metrics]
    payload = spb.DCmd(timestamp=spb.get_current_timestamp(), metrics=tuple(built))
    topic = spb.Topic(message_type=spb.MessageType.DCMD, group_id=group_id, edge_node_id=edge_node_id, device_id=device_id)
    message = spb.Message(topic=topic, payload=payload, qos=spb.QoS.AT_LEAST_ONCE, retain=False)
    client.publish(message, include_dtypes=True)
    return {"group_id": group_id, "edge_node_id": edge_node_id, "device_id": device_id, "metrics_sent": [m.name for m in built]}


@mcp.tool()
def request_node_rebirth(
    group_id: Annotated[str, Field(description="Sparkplug Group ID.")],
    edge_node_id: Annotated[str, Field(description="Sparkplug Edge Node ID.")],
) -> dict[str, Any]:
    """Ask an Edge Node to republish its full NBIRTH (the standard 'Node Control/Rebirth' command).

    Useful after this connector loses metric history (e.g. a restart) or
    suspects a missed message (a gap in the node's seq numbers).

    Returns:
        {group_id, edge_node_id, metrics_sent}
    """
    return send_node_command(
        group_id,
        edge_node_id,
        [{"name": "Node Control/Rebirth", "datatype": "BOOLEAN", "value": True}],
    )


# ---------------------------------------------------------------------------
# Watch sessions (event stream)
# ---------------------------------------------------------------------------


@mcp.tool()
def start_watch(
    group_id: Annotated[str | None, Field(description="Restrict to this Group ID; omit for all groups.")] = None,
    edge_node_id: Annotated[str | None, Field(description="Restrict to this Edge Node ID; omit for all nodes.")] = None,
    device_id: Annotated[str | None, Field(description="Restrict to this Device ID; omit for all devices.")] = None,
    message_types: Annotated[list[str] | None, Field(description=_MESSAGE_TYPE_DESC)] = None,
) -> dict[str, Any]:
    """Start watching Sparkplug B traffic (births, deaths, data, commands, host states).

    Creates a session that buffers matching decoded messages; call
    get_events(session_id) to drain them, and stop_watch(session_id) when done.
    This connector is always subscribed to the full spBv1.0 namespace, so
    watching starts immediately with no additional broker subscription needed.

    Returns:
        {session_id, group_id, edge_node_id, device_id, message_types}
    """
    types: set[str] | None = None
    if message_types:
        types = {t.upper() for t in message_types}
        invalid = types - set(_MESSAGE_TYPES)
        if invalid:
            raise ValueError(f"Invalid message_types: {sorted(invalid)}. Valid: {_MESSAGE_TYPES}")

    session_id = uuid.uuid4().hex
    session = _WatchSession(session_id, group_id, edge_node_id, device_id, types)
    with _watch_sessions_lock:
        _watch_sessions[session_id] = session
    return {
        "session_id": session_id,
        "group_id": group_id,
        "edge_node_id": edge_node_id,
        "device_id": device_id,
        "message_types": sorted(types) if types else None,
    }


@mcp.tool()
def get_events(
    session_id: Annotated[str, Field(description=_SESSION_ID_DESC)],
    max_events: Annotated[int, Field(description="Maximum number of buffered events to return.", ge=1, le=1000)] = 100,
    timeout_seconds: Annotated[float, Field(description="If no events are buffered, wait up to this long for one to arrive.", ge=0.0, le=60.0)] = 0.0,
) -> dict[str, Any]:
    """Drain buffered Sparkplug events collected by a watch session.

    Returns:
        {events: [...], count, buffered_remaining}
    """
    with _watch_sessions_lock:
        session = _watch_sessions.get(session_id)
    if session is None:
        raise ValueError(f"No such watch session: '{session_id}'")

    def _drain(limit: int) -> list[dict[str, Any]]:
        with session.lock:
            n = min(limit, len(session.buffer))
            return [session.buffer.popleft() for _ in range(n)]

    events = _drain(max_events)
    if not events and timeout_seconds > 0:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            session.new_event.wait(timeout=remaining)
            session.new_event.clear()
            events = _drain(max_events)
            if events:
                break

    with session.lock:
        remaining_buffered = len(session.buffer)
    return {"events": events, "count": len(events), "buffered_remaining": remaining_buffered}


@mcp.tool()
def stop_watch(session_id: Annotated[str, Field(description=_SESSION_ID_DESC)]) -> dict[str, Any]:
    """Stop a watch session and discard its buffered events."""
    with _watch_sessions_lock:
        session = _watch_sessions.pop(session_id, None)
    if session is None:
        raise ValueError(f"No such watch session: '{session_id}'")
    return {"session_id": session_id, "stopped": True}


@mcp.tool()
def list_watches() -> dict[str, Any]:
    """List all active watch sessions on this connector.

    Returns:
        {sessions: [{session_id, group_id, edge_node_id, device_id, message_types, buffered_count, event_count, created_at}]}
    """
    with _watch_sessions_lock:
        sessions = list(_watch_sessions.values())
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "group_id": s.group_id,
                "edge_node_id": s.edge_node_id,
                "device_id": s.device_id,
                "message_types": sorted(s.message_types) if s.message_types else None,
                "buffered_count": len(s.buffer),
                "event_count": s.event_count,
                "created_at": s.created_at,
            }
            for s in sessions
        ]
    }


# ---------------------------------------------------------------------------
# MCP transport / entrypoint
# ---------------------------------------------------------------------------

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
    try:
        if transport == "stdio":
            mcp.run()
        else:
            mcp.run(transport=transport, transport_options={"host": host, "port": port})
    finally:
        try:
            _publish_host_state(False)
        except Exception:
            logger.exception("Failed to publish offline host state during shutdown")
        client.disconnect()


if __name__ == "__main__":
    main()
