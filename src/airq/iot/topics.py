"""MQTT topic names, QoS and retain flags (spec 3.2). Single source of truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicSpec:
    pattern: str
    qos: int
    retained: bool


RAW_TELEMETRY = TopicSpec("airq/raw/{station}/telemetry", 1, False)
EDGE_TELEMETRY = TopicSpec("airq/edge/{station}/telemetry", 1, False)
STATUS = TopicSpec("airq/{station}/status", 1, True)
HEARTBEAT = TopicSpec("airq/{station}/heartbeat", 0, False)
WARNINGS = TopicSpec("airq/warnings/{station}", 1, False)
EDGE_STATS = TopicSpec("airq/edge/stats", 0, False)
CMD_STATION = TopicSpec("airq/cmd/{station}", 1, False)
CMD_FLEET = TopicSpec("airq/cmd/fleet", 1, False)
CMD_NET = TopicSpec("airq/cmd/net", 1, False)
CMD_ACK = TopicSpec("airq/cmd/ack/{station}", 1, False)

# Wildcard subscriptions
RAW_ALL = "airq/raw/+/telemetry"
EDGE_ALL = "airq/edge/+/telemetry"
STATUS_ALL = "airq/+/status"
HEARTBEAT_ALL = "airq/+/heartbeat"

ONLINE = "online"
OFFLINE = "offline"


def topic(spec: TopicSpec, station: str | None = None) -> str:
    """Concrete topic for a spec; stations may not contain MQTT wildcards or '/'."""
    if station is None:
        if "{station}" in spec.pattern:
            raise ValueError(f"{spec.pattern} needs a station")
        return spec.pattern
    if any(ch in station for ch in "/+#") or not station:
        raise ValueError(f"Invalid station name: {station!r}")
    return spec.pattern.format(station=station)


def station_from_topic(topic_name: str) -> str:
    """Extract the station from raw/edge telemetry, status, heartbeat, warnings, cmd topics."""
    parts = topic_name.split("/")
    if parts[:2] in (["airq", "raw"], ["airq", "edge"], ["airq", "warnings"]) and len(parts) >= 3:
        return parts[2]
    if parts[:3] == ["airq", "cmd", "ack"] and len(parts) == 4:
        return parts[3]
    if parts[:2] == ["airq", "cmd"] and len(parts) == 3:
        return parts[2]
    if len(parts) == 3 and parts[0] == "airq" and parts[2] in ("status", "heartbeat"):
        return parts[1]
    raise ValueError(f"Cannot extract station from topic {topic_name!r}")
