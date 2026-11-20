"""Control plane client: publishes Senaryo Kontrol commands and collects their acks.

dashboard -> API -> Controller -> MQTT airq/cmd/* -> devices / fleet / edge -> airq/cmd/ack/*
The Controller never touches the database; the ingest service logs commands and acks in
`interventions` (single writer). Used by the API's `/control/*` endpoints.
"""

from __future__ import annotations

import threading
import uuid

from airq.iot import topics
from airq.iot.mqtt_client import connect_blocking, disconnect, make_client
from airq.iot.schemas import (
    ALL_TARGET,
    Ack,
    Command,
    EdgeControl,
    FleetControl,
    NetControl,
)

Message = Command | FleetControl | NetControl | EdgeControl


def new_cmd_id() -> str:
    return str(uuid.uuid4())


def topic_for(msg: Message) -> str:
    """Station commands go to their own topic; everything fleet-wide uses `airq/cmd/fleet`."""
    if isinstance(msg, Command):
        if msg.target == ALL_TARGET:
            return topics.topic(topics.CMD_FLEET)
        return topics.topic(topics.CMD_STATION, msg.target)
    if isinstance(msg, FleetControl):
        return topics.topic(topics.CMD_FLEET)
    if isinstance(msg, NetControl):
        return topics.topic(topics.CMD_NET)
    return topics.topic(topics.CMD_EDGE)


class Controller:
    def __init__(self, host: str, port: int, client_id: str = "api-control"):
        self.host, self.port = host, port
        self._acks: dict[str, list[Ack]] = {}
        self._cv = threading.Condition()
        self._client = make_client(client_id)
        self._client.on_message = self._on_ack

    def start(self) -> None:
        connect_blocking(self._client, self.host, self.port)
        self._client.subscribe(topics.CMD_ACK_ALL, qos=topics.CMD_ACK.qos)

    def stop(self) -> None:
        disconnect(self._client)

    def _on_ack(self, _c, _u, msg) -> None:
        try:
            ack = Ack.from_json(msg.payload)
        except ValueError:
            return
        with self._cv:
            self._acks.setdefault(ack.cmd_id, []).append(ack)
            self._cv.notify_all()

    def send(self, msg: Message) -> str:
        """Publish a command (QoS 1) and return its cmd_id."""
        self._client.publish(topic_for(msg), msg.to_json(), qos=1).wait_for_publish(timeout=5)
        return msg.cmd_id

    def wait_acks(self, cmd_id: str, expect: int = 1, timeout_s: float = 5.0) -> list[Ack]:
        """Block until `expect` acks for `cmd_id` arrived (or the timeout); returns what came."""
        with self._cv:
            self._cv.wait_for(lambda: len(self._acks.get(cmd_id, [])) >= expect, timeout_s)
            return list(self._acks.get(cmd_id, []))
