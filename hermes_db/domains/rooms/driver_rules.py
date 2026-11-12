"""Shared room validation and exact wire values; no Native storage service."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from hermes_db.domains.rooms.rules import bounded_int, canonical_json, compact_json, identifier, text
from typing import Any, Callable, Literal, NamedTuple, get_args
import hashlib
import json
import math
import sqlite3
Clock = Callable[[], float]
TaskStatus = Literal["queued", "running", "settled", "failed", "cancelled", "indeterminate", "deferred", "stopping"]
MAX_IDENTIFIER_CHARS = 128
MAX_PROMPT_BYTES = 128 * 1024
MAX_RESULT_JSON_BYTES = 256 * 1024
TERMINAL_TASK_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_RETAINED_TERMINAL_TASKS = 2048
MAX_TASK_PRUNE_BATCH = 1000
TASK_STATUSES = frozenset(get_args(TaskStatus))
TERMINAL_STATUSES = frozenset({"settled", "failed", "cancelled"})
_TASK_PAYLOAD_REQUIRED_FIELDS = frozenset({"target_profile", "prompt", "source_event_seq"})
_TASK_PAYLOAD_OPTIONAL_FIELDS = frozenset({"target_member_id", "input_context", "attachments", "lead_routing"})
_TASK_COLUMN_ORDER = (
    "room_id", "task_id", "thread_id", "turn_id", "source_event_seq", "payload_json", "payload_digest", "status",
    "execution_generation", "cancel_generation", "run_gateway_id", "run_process_generation", "run_lease_generation",
    "cancel_id", "settlement_id", "settlement_status", "result_json", "created_at", "updated_at", "started_at",
    "terminal_at", "indeterminate_at")

class DriverStateError(ValueError): """Base class for invalid or conflicting driver-state operations."""

class DriverValidationError(DriverStateError): """Raised when an identifier, clock, TTL, or payload is invalid."""

class RoomUnavailableError(DriverStateError): """Raised when the hosted room does not exist or was disbanded."""

class LeaseHeldError(DriverStateError): """Raised when another unexpired driver generation owns the room."""

class StaleLeaseError(DriverStateError): """Raised when a lease generation can no longer mutate room state."""

class TaskConflictError(DriverStateError): """Raised when an idempotency key is reused for different task state."""

class StaleTaskError(DriverStateError): """Raised when an obsolete task attempt or cancellation tries to commit."""

class InvalidTaskTransitionError(DriverStateError): """Raised when a requested task transition is not allowed."""
_identifier = partial(identifier, error=DriverValidationError, max_chars=MAX_IDENTIFIER_CHARS)
_bounded_int = partial(bounded_int, error=DriverValidationError)
_canonical_json = partial(
    canonical_json, error=DriverValidationError, label="result", max_bytes=MAX_RESULT_JSON_BYTES, ensure_ascii=True)

def _finite(compute: Callable[[], Any], message: str, *, positive: bool = False) -> float:
    try:
        value = float(compute())
    except (TypeError, ValueError, OverflowError) as exc:
        raise DriverValidationError(message) from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise DriverValidationError(message)
    return value

def _timestamp(clock: Clock) -> float:
    if not callable(clock):
        raise DriverValidationError("clock must be callable")
    return _finite(clock, "clock must return a finite number")

def _lease_window(ttl_seconds: Any, clock: Clock) -> tuple[float, float]:
    """Validate ttl (first) and clock -> ``(now, expires_at)``; the sum itself must stay finite."""
    ttl = _finite(lambda: ttl_seconds, "ttl_seconds must be a finite positive number", positive=True)
    now = _timestamp(clock)
    if not math.isfinite(now + ttl):
        raise DriverValidationError("lease expiry must be finite")
    return now, now + ttl

def validate_bound_task_manifest(value: Any) -> list[dict[str, Any]]:
    """Validate store metadata plus the exact source event for each task input."""
    from hermes_db.domains.rooms.attachments.rules import validate_task_manifest
    if not isinstance(value, list) or not value:
        raise DriverValidationError('attachments must be a non-empty list')
    if any(not isinstance(item, Mapping) or 'event_id' not in item for item in value):
        raise DriverValidationError('task attachment requires event_id')
    event_ids = [_identifier(item['event_id'], label='attachment event_id') for item in value]
    try:
        manifest = validate_task_manifest([{key: val for key, val in item.items() if key != 'event_id'} for item in value])
    except ValueError as exc:
        raise DriverValidationError(str(exc)) from exc
    return [{**item, 'event_id': event_id} for item, event_id in zip(manifest, event_ids)]

def _task_payload(value: Any) -> tuple[dict[str, Any], str, str]:
    if not isinstance(value, dict):
        raise DriverValidationError("payload must be an object")
    unknown = set(value) - _TASK_PAYLOAD_REQUIRED_FIELDS - _TASK_PAYLOAD_OPTIONAL_FIELDS
    missing = _TASK_PAYLOAD_REQUIRED_FIELDS - set(value)
    if unknown:
        raise DriverValidationError(f"unknown payload fields: {', '.join(sorted(unknown))}")
    if missing:
        raise DriverValidationError(f"missing payload fields: {', '.join(sorted(missing))}")
    target_profile = _identifier(value["target_profile"], label="target_profile")
    prompt = text(value["prompt"], error=DriverValidationError, label="prompt", max_bytes=MAX_PROMPT_BYTES, strip=False)
    source_event_seq = _bounded_int(
        value["source_event_seq"], message="source_event_seq must be a positive integer", low=1)
    normalized = {"target_profile": target_profile, "prompt": prompt, "source_event_seq": source_event_seq}
    if "input_context" in value:
        from gateway.hosted_room_task_input import validate_task_input

        try:
            normalized["input_context"] = validate_task_input(value["input_context"])
        except ValueError as exc:
            raise DriverValidationError(str(exc)) from exc
    if "target_member_id" in value:
        normalized["target_member_id"] = _identifier(value["target_member_id"], label="target_member_id")
    if "attachments" in value:
        normalized["attachments"] = validate_bound_task_manifest(value["attachments"])
    if "lead_routing" in value:
        # Present only on a lead's routing turn, and then exactly true: absence is an ordinary member turn.
        if value["lead_routing"] is not True:
            raise DriverValidationError("lead_routing must be true when present")
        normalized["lead_routing"] = True
    encoded = compact_json(normalized)
    return normalized, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class TaskIdentity:
    """Stable identity for one admitted room turn."""
    room_id: str
    task_id: str
    thread_id: str
    turn_id: str

    def __post_init__(self) -> None:
        for field in ("room_id", "task_id", "thread_id", "turn_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), label=field))

@dataclass(frozen=True)
class DriverLease:
    """A fenced lease held by one gateway process incarnation."""
    room_id: str
    gateway_id: str
    authority_epoch: int
    process_generation: str
    lease_generation: int
    expires_at: float
    reclaimed: bool = False

@dataclass(frozen=True)
class TaskAttempt:
    """The exact running generation authorized to settle one task."""
    identity: TaskIdentity
    lease: DriverLease
    execution_generation: int
    cancel_generation: int

def _lease_from_row(row: sqlite3.Row | dict[str, Any], *, reclaimed: bool = False) -> DriverLease:
    return DriverLease(
        room_id=row["room_id"], gateway_id=row["gateway_id"], authority_epoch=int(row["authority_epoch"]),
        process_generation=row["process_generation"], lease_generation=int(row["lease_generation"]),
        expires_at=float(row["expires_at"]), reclaimed=reclaimed)

def _task_identity_from_row(row: sqlite3.Row) -> TaskIdentity:
    return TaskIdentity(
        room_id=row["room_id"], task_id=row["task_id"], thread_id=row["thread_id"], turn_id=row["turn_id"])

def _optional(cast: Callable[[Any], Any]) -> Callable[[Any], Any]:
    return lambda value: cast(value) if value is not None else None
_TASK_VIEW_CASTS: dict[str, Callable[[Any], Any]] = {'execution_generation': int, 'cancel_generation': int, 'run_lease_generation': _optional(int), 'result_json': _optional(json.loads), 'created_at': float, 'updated_at': float, 'started_at': _optional(float), 'terminal_at': _optional(float), 'indeterminate_at': _optional(float)}

def _task_from_row(row: sqlite3.Row, *, idempotent: bool = False) -> dict[str, Any]:
    try:
        payload, encoded_payload, payload_digest = _task_payload(json.loads(row["payload_json"]))
    except (TypeError, json.JSONDecodeError, DriverValidationError) as exc:
        raise TaskConflictError("stored task payload is invalid") from exc
    if (encoded_payload, payload_digest, payload["source_event_seq"]) != (
        row["payload_json"], row["payload_digest"], int(row["source_event_seq"])):
        raise TaskConflictError("stored task payload failed its integrity check")
    task: dict[str, Any] = {"identity": _task_identity_from_row(row), "payload": payload}
    for column in _TASK_COLUMN_ORDER[_TASK_COLUMN_ORDER.index("payload_digest"):]:
        task["result" if column == "result_json" else column] = _TASK_VIEW_CASTS.get(column, lambda v: v)(row[column])
    task["idempotent"] = idempotent
    return task

def _run_fence(lease: DriverLease) -> tuple[str, str, int]:
    """The ``_RUN_FENCE`` bind order: (gateway_id, process_generation, lease_generation)."""
    return lease.gateway_id, lease.process_generation, lease.lease_generation

def _lease_row_matches(row: sqlite3.Row | None, lease: DriverLease) -> bool:
    return row is not None and (
        row["gateway_id"], int(row["authority_epoch"]), row["process_generation"], int(row["lease_generation"])
    ) == (lease.gateway_id, lease.authority_epoch, lease.process_generation, lease.lease_generation)

def _check_same_room(lease: DriverLease, identity: TaskIdentity) -> None:
    if lease.room_id != identity.room_id:
        raise DriverValidationError("lease and task belong to different rooms")

def _cancel_generation(value: int) -> int:
    # Deliberately accepts bool (a bool is an int); do not swap for non_negative_int.
    if not isinstance(value, int) or value < 0:
        raise DriverValidationError("expected_cancel_generation must be non-negative")
    return value

def _expected_generations(
    lease: DriverLease, identity: TaskIdentity, execution_generation: int, cancel_generation: int) -> None:
    _check_same_room(lease, identity)
    if not isinstance(execution_generation, int) or execution_generation < 1:
        raise DriverValidationError("expected_execution_generation must be a positive integer")
    _cancel_generation(cancel_generation)

def _terminal_settlement_id(settlement_id: Any, status: Any) -> str:
    settlement_id = _identifier(settlement_id, label="settlement_id")
    if status not in {"settled", "failed"}:
        raise DriverValidationError("status must be 'settled' or 'failed'")
    return settlement_id

def _settlement(
    settlement_id: Any, status: Any, result: Any, clock: Clock
) -> tuple[float, Callable[[sqlite3.Row], Any], tuple[Any, ...]]:
    """Validate one terminal settlement -> (now, replay predicate, ``_SETTLE_SET`` params); the replay treats an
    identical committed settlement as idempotent and a different one as a conflict."""
    settlement_id = _terminal_settlement_id(settlement_id, status)
    result_json = _canonical_json(result)
    now = _timestamp(clock)
    def replay(row: sqlite3.Row) -> dict[str, Any] | None:
        if row["settlement_id"] is None:
            return None
        if (row["settlement_id"], row["settlement_status"], row["result_json"]) == (settlement_id, status, result_json):
            return _task_from_row(row, idempotent=True)
        raise TaskConflictError("task already has a different terminal settlement")
    return now, replay, (status, settlement_id, status, result_json, now, now)

def _cancel_replay(cancel_id: str, status: str = "cancelled") -> Callable[[sqlite3.Row], Any]:
    """Replay predicate: same cancel_id already committed in ``status``."""
    return lambda row: (
        _task_from_row(row, idempotent=True) if row["status"] == status and row["cancel_id"] == cancel_id else None)

def _generations_match(row: sqlite3.Row, status: str, execution_generation: int, cancel_generation: int) -> bool:
    return (row["status"], int(row["execution_generation"]), int(row["cancel_generation"])) == (
        status, execution_generation, cancel_generation)

def _require_cancel_generation(row: sqlite3.Row, expected_cancel_generation: int) -> None:
    if int(row["cancel_generation"]) != expected_cancel_generation:
        raise StaleTaskError("task cancellation generation changed")
_HOMES = 'gateway.hosted.member_homes.v1:'

def _key(room_id, member_id):
    return _HOMES + json.dumps([room_id, member_id], separators=(',', ':'))
_LIVE_ATTEMPT = frozenset({'running', 'stopping', 'deferred', 'indeterminate'})
_STOPPING = frozenset({'stopping', 'deferred'})

def _attempt_prefix(room_id, member_id):
    return _HOMES + json.dumps([room_id, member_id], separators=(',', ':'))[:-1] + ','
DriverStateError.__module__ = 'gateway.hosted_room_driver'
DriverValidationError.__module__ = 'gateway.hosted_room_driver'
RoomUnavailableError.__module__ = 'gateway.hosted_room_driver'
LeaseHeldError.__module__ = 'gateway.hosted_room_driver'
StaleLeaseError.__module__ = 'gateway.hosted_room_driver'
TaskConflictError.__module__ = 'gateway.hosted_room_driver'
StaleTaskError.__module__ = 'gateway.hosted_room_driver'
InvalidTaskTransitionError.__module__ = 'gateway.hosted_room_driver'
TaskIdentity.__module__ = 'gateway.hosted_room_driver'
DriverLease.__module__ = 'gateway.hosted_room_driver'
TaskAttempt.__module__ = 'gateway.hosted_room_driver'


SHOWN_TASK_STATUSES = ("queued", "running", "stopping", "indeterminate", "deferred")


class RoomChangeRows(NamedTuple):
    next_seq: int
    revision: int
    tasks: tuple
