"""Shared room validation and exact wire values; no Native storage service."""
from __future__ import annotations
from functools import partial
from hermes_db.domains.rooms.rules import MAX_ACTOR_ID_CHARS, HostedRoomError, _actor_json, _payload_json, _validate_identifier
from hermes_db.domains.rooms.rules import bounded_int, utf8_len
from typing import Any
import json
MAX_REPLICA_ROOMS = 256
MAX_REPLICA_EVENT_BYTES = 256 * 1024 * 1024
_SYSTEM_ACTOR = {"kind": "system", "id": "authority-control"}

class ReplicaError(HostedRoomError): """Base class for invalid or conflicting replica operations."""

class ReplicaGapError(ReplicaError): """A page does not start at the replica's next expected sequence."""

class ReplicaEpochRegressionError(ReplicaError): """A page or demotion carries an older authority epoch than stored."""
_positive_int = partial(bounded_int, error=ReplicaError, low=1)

def _control_event(kind: str, epoch: int, payload: dict[str, Any]) -> tuple[str, str, str, str]:
    """(event_id, kind, actor_json, payload_json) of the system ``authority.<kind>`` control event for ``epoch``."""
    return f"system:authority-{kind}:{epoch}", f"authority.{kind}", _actor_json(_SYSTEM_ACTOR), _payload_json(payload)

def _event_bytes(event: dict[str, Any]) -> int:
    return utf8_len(
        str(event["event_id"]), str(event["kind"]),
        json.dumps(event["actor"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":")))

def _validate_page(page: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(page, dict):
        raise ReplicaError("page must be an object")
    events, authority = page.get("events"), page.get("authority")
    if not isinstance(events, list):
        raise ReplicaError("page.events must be a list")
    if not isinstance(authority, dict):
        raise ReplicaError("page.authority is required for replication")
    gateway_id = _validate_identifier(
        authority.get("gateway_id"), label="page.authority.gateway_id", max_chars=MAX_ACTOR_ID_CHARS)
    epoch = _positive_int(authority.get("epoch"), message="page.authority.epoch must be a positive integer")
    previous_seq: int | None = None
    for event in events:
        if not isinstance(event, dict):
            raise ReplicaError("page events must be objects")
        seq = _positive_int(event.get("seq"), message="event.seq must be a positive integer")
        if previous_seq is not None and seq != previous_seq + 1:
            raise ReplicaGapError("page events must be contiguous")
        previous_seq = seq
        for field in ("event_id", "kind"):
            if not isinstance(event.get(field), str) or not event[field]:
                raise ReplicaError(f"event.{field} must be a non-empty string")
        if not isinstance(event.get("actor"), dict):
            raise ReplicaError("event.actor must be an object")
        if "payload" not in event:
            raise ReplicaError("event.payload is required")
    return events, {"gateway_id": gateway_id, "epoch": epoch}
ReplicaError.__module__ = 'gateway.hosted_room_replicas'
ReplicaGapError.__module__ = 'gateway.hosted_room_replicas'
ReplicaEpochRegressionError.__module__ = 'gateway.hosted_room_replicas'
