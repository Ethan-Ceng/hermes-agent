"""Shared hosted-room limits, validation and row projections; no storage or Profile I/O."""
from __future__ import annotations
import hashlib
import json
import math
import re
import sqlite3
import time
from functools import partial
from typing import Any, Callable, Mapping
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

def bounded_grant_expiry(value: float, *, now: float, horizon: float) -> float:
    """An unreadable unsigned horizon cannot prove expiry or retain a grant forever."""
    expiry = float(value)
    return min(expiry, now + horizon) if math.isfinite(expiry) else now + horizon

def identifier(
    value: Any, *, label: str, error: type[Exception], max_chars: int = 128,
    pattern: re.Pattern[str] | None = IDENTIFIER_RE, invalid: str | None = None) -> str:
    """Strip and validate a bounded string; ``pattern=None`` skips the shape check."""
    if not isinstance(value, str):
        raise error(f"{label} must be a string")
    value = value.strip()
    if not value or len(value) > max_chars or (pattern is not None and not pattern.fullmatch(value)):
        raise error(invalid or f"invalid {label}")
    return value

def bounded_int(value: Any, *, error: type[Exception], message: str, low: int = 0, high: int | None = None) -> int:
    """Reject bools, non-ints and values outside ``[low, high]`` (``message`` is the exact text)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        raise error(message)
    return value

def exact_fields(
    value: Any, *, label: str, required: frozenset[str] | set[str], optional: frozenset[str] | set[str] = frozenset(),
    error: type[Exception], not_object: str | None = None, missing_fmt: str = "{label} is missing fields: {fields}",
    unknown_fmt: str = "{label} has unknown fields: {fields}") -> Mapping[str, Any]:
    """Require exactly ``required`` (+ any ``optional``) keys; formats name the offenders sorted."""
    if not isinstance(value, Mapping):
        raise error(not_object or f"{label} must be an object")
    keys = frozenset(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise error(missing_fmt.format(label=label, fields=", ".join(sorted(missing))))
    if unknown:
        raise error(unknown_fmt.format(label=label, fields=", ".join(sorted(unknown))))
    return value

def text(value: Any, *, error: type[Exception], label: str, max_bytes: int, strip: bool = True) -> str:
    """Non-blank string bounded by ``max_bytes`` of UTF-8; ``strip=False`` keeps and measures the raw text."""
    if not isinstance(value, str):
        raise error(f"{label} must be a string")
    if not value.strip():
        raise error(f"{label} must not be empty")
    if strip:
        value = value.strip()
    if len(value.encode("utf-8")) > max_bytes:
        raise error(f"{label} is too large")
    return value

def compact_json(value: Any, *, ensure_ascii: bool = True) -> str:
    """Sorted-key, separator-free JSON (the digest/storage canonical form)."""
    return json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=True, separators=(",", ":"))

def canonical_json(value: Any, *, error: type[Exception], label: str, max_bytes: int, ensure_ascii: bool) -> str:
    """``compact_json`` bounded by ``max_bytes`` of UTF-8; unserializable input raises ``error``."""
    try:
        encoded = compact_json(value, ensure_ascii=ensure_ascii)
    except (TypeError, ValueError, RecursionError) as exc:
        raise error(f"{label} must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise error(f"{label} is too large")
    return encoded

def utf8_len(*parts: str) -> int:
    return len("".join(parts).encode("utf-8"))

def clock(now: float | None) -> float:
    """``now`` as a float, or the current wall clock when ``None``."""
    return time.time() if now is None else float(now)
MAX_ROOM_ID_CHARS = 128
MAX_EVENT_ID_CHARS = 128
MAX_ROOM_NAME_CHARS = 200
MAX_EVENT_KIND_CHARS = 64
MAX_ACTOR_ID_CHARS = 128
MAX_ACTOR_LABEL_CHARS = 200
MAX_MEMBERS = 128
MAX_MEMBERS_JSON_BYTES = 128 * 1024
MAX_EVENT_JSON_BYTES = 256 * 1024
MAX_LOG_LIMIT = 500
MAX_LOG_PAGE_BYTES = 2 * 1024 * 1024
MAX_ROOM_LIST_LIMIT = 500
MAX_ACTIVE_ROOMS = 256
MAX_DISBANDED_ROOM_TOMBSTONES = 512
DISBANDED_ROOM_RETENTION_SECONDS = 90 * 24 * 60 * 60
MAX_EVENTS_PER_ROOM = 50_000
MAX_ROOM_EVENT_BYTES = 256 * 1024 * 1024
MAX_GATEWAY_EVENT_BYTES = 16 * 1024 * 1024
CONTROL_EVENT_COUNT_RESERVE = 64
CONTROL_EVENT_BYTE_RESERVE = 1024 * 1024
_EVENT_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_CONTROL_EVENT_KINDS = frozenset({"authority.claimed", "authority.lost", "room.disbanded", "room.stop_requested"})
_EVENT_KINDS_BY_ACTOR = {
    "user": frozenset({"message.user"}), "member": frozenset({"message.member"}),
    "gateway": frozenset({
        "member.unavailable", "room.activity", "room.assignment", "room.continued", "room.routed", "room.stop_requested",
        "turn.deferred", "turn.reassigned",
        "turn.cancelled", "turn.failed", "turn.settled", "turn.started"}),
    "system": frozenset({
        "authority.claimed", "authority.lost", "room.context_set", "room.created", "room.disbanded",
        "room.members_changed", "room.renamed"})}
_OPTIONAL_ACTOR_FIELDS = (
    ("display_name", MAX_ACTOR_LABEL_CHARS), ("profile", MAX_ACTOR_ID_CHARS), ("connection_id", MAX_ACTOR_ID_CHARS))
_ACTOR_FIELDS = frozenset({"kind", "id", *(field for field, _ in _OPTIONAL_ACTOR_FIELDS)})
_LINK_COLUMNS = (
    "room_id", "member_id", "target_url", "target_profile", "grant", "catalog_json", "cancellation_scope_id",
    "trace_id", "transport_security", "status", "updated_at")

class HostedRoomError(ValueError): """Base class for invalid or conflicting hosted-room operations."""

class RoomNotFoundError(HostedRoomError): """Raised when a room does not exist or has been disbanded."""

class RoomHistoryExpiredError(RoomNotFoundError):
    """Raised when a retired room remains reserved after history compaction."""
    reason = "room_history_expired"

class RoomConflictError(HostedRoomError): """Raised when an idempotency key is reused for different room state."""

class RoomHeldGrantsPendingError(HostedRoomError):
    """Retry Disband after revoking grants received since its last sweep."""
    reason = "room_disbanding_retry"

class RoomStopPendingError(HostedRoomError, RuntimeError):
    """Expected Stop refusal; retain RuntimeError compatibility for direct service callers."""
    reason = "room_stop_pending"

class RoomProbeUnavailableError(HostedRoomError):
    """Raised when a non-blocking ownership probe cannot read the room store."""

class EventConflictError(HostedRoomError): """Raised when an event id is reused with different immutable content."""

class EventCursorConflictError(HostedRoomError):
    """Raised when new room events invalidate an uncommitted publication plan."""

class EventAttachmentConflictError(EventCursorConflictError):
    """A publication lost its file commitments; use the same fresh-plan retry."""

class AuthorityConflictError(HostedRoomError):
    """Raised when a stale room authority attempts to mutate hosted state."""
    reason = "authority_conflict"

class AuthoritySupersededError(AuthorityConflictError):
    """Raised when a successful authority claim was later superseded."""
_canonical_json = partial(canonical_json, error=HostedRoomError, ensure_ascii=False)
_validate_identifier = partial(identifier, error=HostedRoomError)
_room_id = partial(_validate_identifier, label="room_id", max_chars=MAX_ROOM_ID_CHARS)
_event_id = partial(_validate_identifier, label="event_id", max_chars=MAX_EVENT_ID_CHARS)
_actor_json = partial(_canonical_json, label="actor", max_bytes=4 * 1024)
_payload_json = partial(_canonical_json, label="payload", max_bytes=MAX_EVENT_JSON_BYTES)
_bounded_int = partial(bounded_int, error=HostedRoomError)
_validate_room_name = partial(
    _validate_identifier, label="name", max_chars=MAX_ROOM_NAME_CHARS, pattern=None, invalid="invalid room name")
_validate_event_kind = partial(
    _validate_identifier, label="kind", max_chars=MAX_EVENT_KIND_CHARS, pattern=_EVENT_KIND_RE,
    invalid="invalid event kind")

def _actor_id(value: Any, label: str) -> str:
    return _validate_identifier(value, label=label, max_chars=MAX_ACTOR_ID_CHARS)

def _require_positive_int(value: Any, label: str) -> int:
    return _bounded_int(value, message=f"{label} must be a positive integer", low=1)

def _bounded_limit(value: Any, maximum: int) -> int:
    return _bounded_int(value, message=f"limit must be between 1 and {maximum}", low=1, high=maximum)

def _non_negative(value: Any, label: str) -> int:
    return _bounded_int(value, message=f"{label} must be a non-negative integer")

def _system_actor_json(actor_id: str) -> str:
    return _actor_json({"kind": "system", "id": actor_id})

def _claim_payload_json(previous_gateway_id: str, new_gateway_id: str, epoch: int) -> str:
    return _payload_json(
        {"previous_gateway_id": previous_gateway_id, "authority_gateway_id": new_gateway_id, "authority_epoch": epoch})

def _validate_members(value: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, list):
        raise HostedRoomError("members must be a list")
    if len(value) > MAX_MEMBERS:
        raise HostedRoomError("too many room members")
    if not all(isinstance(member, dict) for member in value):
        raise HostedRoomError("each room member must be an object")
    members = [dict(member) for member in value]
    return members, _canonical_json(members, label="members", max_bytes=MAX_MEMBERS_JSON_BYTES)

def _validate_actor(value: Any, *, kind: str) -> tuple[dict[str, str], str]:
    if not isinstance(value, dict):
        raise HostedRoomError("actor must be an object")
    unknown = set(value) - _ACTOR_FIELDS
    if unknown:
        raise HostedRoomError(f"unknown actor fields: {', '.join(sorted(unknown))}")
    actor_kind = value.get("kind")
    if not isinstance(actor_kind, str) or actor_kind not in _EVENT_KINDS_BY_ACTOR:
        raise HostedRoomError("invalid actor.kind")
    if kind not in _EVENT_KINDS_BY_ACTOR[actor_kind]:
        raise HostedRoomError(f"actor kind '{actor_kind}' cannot append '{kind}'")
    actor = {"kind": actor_kind, "id": _actor_id(value.get("id"), "actor.id")}
    for field, max_chars in _OPTIONAL_ACTOR_FIELDS:
        field_value = value.get(field)
        if field_value is None:
            continue
        if not isinstance(field_value, str):
            raise HostedRoomError(f"actor.{field} must be a string")
        if len(field_value := field_value.strip()) > max_chars:
            raise HostedRoomError(f"actor.{field} is too long")
        if field_value:
            actor[field] = field_value
    return actor, _actor_json(actor)

def _require_authority(room: sqlite3.Row, gateway_id: str, epoch: int, message: str) -> None:
    if str(room["authority_gateway_id"]) != gateway_id or int(room["authority_epoch"]) != epoch:
        raise AuthorityConflictError(message)

def _room_from_row(row: sqlite3.Row, *, idempotent: bool = False) -> dict[str, Any]:
    keys = row.keys()  # sqlite3.Row: ``x in row`` scans values, so ``.keys()`` is load-bearing.
    return {
        "room_id": row["room_id"], "name": row["name"], "members": json.loads(row["members_json"]),
        "authority_gateway_id": row["authority_gateway_id"], "authority_epoch": int(row["authority_epoch"]),
        "revision": int(row["revision"]), "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]), "idempotent": idempotent,
        **({"disbanded_at": float(row["disbanded_at"])} if "disbanded_at" in keys and row["disbanded_at"] is not None
           else {}),
        **({"latest_seq": int(row["next_seq"]) - 1} if "next_seq" in keys else {})}

def _event_from_row(row: sqlite3.Row, *, idempotent: bool = False) -> dict[str, Any]:
    epoch = row["authority_epoch"]
    return {
        "room_id": row["room_id"], "seq": int(row["seq"]), "event_id": row["event_id"], "kind": row["kind"],
        "actor": json.loads(row["actor_json"]), "authority_epoch": int(epoch) if epoch is not None else None,
        "payload": json.loads(row["payload_json"]), "created_at": float(row["created_at"]), "idempotent": idempotent}

def _event_content(row: sqlite3.Row) -> tuple[Any, Any, Any, Any]:
    """The immutable (kind, actor_json, authority_epoch, payload_json) an event id is bound to."""
    return row["kind"], row["actor_json"], row["authority_epoch"], row["payload_json"]

def grant_digest(grant: str) -> str:
    """The non-secret key an owed revoke is stored and logged under."""
    return hashlib.sha256(grant.encode("utf-8")).hexdigest()
MAX_OWED_REVOKE_SECONDS = 30 * 24 * 60 * 60
MAX_OWED_REVOKES_PER_MEMBER = 4
MAX_OWED_REVOKES = 512

class OwedRevokesFullError(HostedRoomError):
    """No room is left to record an owed revoke, while the grant it names may still pass."""

def _claim_values(claims: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    return {key: str(claims.get(key) or "") for key in keys}

def _room_grant_scope_key(claims: Mapping[str, Any]) -> str:
    """Return a stable non-secret key for one room/home/target/profile scope."""
    fields = _claim_values(claims, (
        "room_id", "home_install_id", "authority_gateway_id", "authority_epoch", "member_id", "target_install_id",
        "target_profile"))
    if not all(fields.values()):
        raise HostedRoomError("room grant scope is incomplete")
    return hashlib.sha256(compact_json(fields).encode("utf-8")).hexdigest()

def _reservation_claims(claims: Mapping[str, Any]) -> tuple[str, str, str, str, int]:
    """Validate (room_id, member_id, target_profile, authority_gateway_id, authority_epoch)."""
    values = (
        _room_id(claims.get("room_id")),
        *(_actor_id(claims.get(key), key) for key in ("member_id", "target_profile", "authority_gateway_id")),
        int(claims.get("authority_epoch") or 0))
    if values[4] < 1:
        raise HostedRoomError("authority_epoch must be positive")
    return values

def _reservation_superseded(row: sqlite3.Row, gateway_id: str, epoch: int) -> bool:
    """A newer epoch, or the same epoch under another gateway, outranks this claim."""
    row_epoch = int(row["authority_epoch"])
    return row_epoch > epoch or (row_epoch == epoch and str(row["authority_gateway_id"]) != gateway_id)
AuthorityConflictError.__module__ = 'gateway.hosted_rooms'
AuthoritySupersededError.__module__ = 'gateway.hosted_rooms'
EventAttachmentConflictError.__module__ = 'gateway.hosted_rooms'
EventConflictError.__module__ = 'gateway.hosted_rooms'
EventCursorConflictError.__module__ = 'gateway.hosted_rooms'
HostedRoomError.__module__ = 'gateway.hosted_rooms'
OwedRevokesFullError.__module__ = 'gateway.hosted_rooms'
RoomConflictError.__module__ = 'gateway.hosted_rooms'
RoomHeldGrantsPendingError.__module__ = 'gateway.hosted_rooms'
RoomHistoryExpiredError.__module__ = 'gateway.hosted_rooms'
RoomNotFoundError.__module__ = 'gateway.hosted_rooms'
RoomProbeUnavailableError.__module__ = 'gateway.hosted_rooms'
RoomStopPendingError.__module__ = 'gateway.hosted_rooms'
from dataclasses import dataclass
MAX_PURPOSE_CHARS = 500
MAX_NOTES_BYTES = 4 * 1024
CONTEXT_EVENT_KIND = "room.context_set"
_CONTEXT_ACTOR = {"kind": "system", "id": "room-control"}
ROUTING_MODES = ("everyone", "lead", "auto")
_EMPTY_CONTEXT = {"purpose": "", "notes": "", "routing": "everyone", "lead_member_id": ""}

def validate_context(purpose: Any, notes: Any, routing: Any='everyone', lead_member_id: Any='') -> dict[str, str]:
    """Normalize one room settings record; purpose and notes may be empty (clears them). ``lead`` routing
    needs a lead; ``everyone`` routing never keeps one."""
    if not all(isinstance(value, str) for value in (purpose, notes, routing, lead_member_id)):
        raise HostedRoomError('purpose, notes, routing and lead_member_id must be strings')
    purpose = ' '.join(purpose.split())
    notes = notes.strip()
    if len(purpose) > MAX_PURPOSE_CHARS:
        raise HostedRoomError(f'purpose must be at most {MAX_PURPOSE_CHARS} characters')
    if len(notes.encode('utf-8')) > MAX_NOTES_BYTES:
        raise HostedRoomError(f'notes must be at most {MAX_NOTES_BYTES} bytes')
    if routing not in ROUTING_MODES:
        raise HostedRoomError("routing must be 'everyone', 'lead' or 'auto'")
    if routing == 'lead' and (not lead_member_id.strip()):
        raise HostedRoomError('lead routing needs a lead_member_id')
    return {'purpose': purpose, 'notes': notes, 'routing': routing, 'lead_member_id': lead_member_id.strip() if routing == 'lead' else ''}
MAX_ACTIVE_POLICY_EVENTS = 64
MAX_ACTIVE_RETRY_RECEIPTS = 64
MAX_THREAD_TRANSCRIPT_EVENTS = 24
_TRANSCRIPT_SCHEMA_VERSION = 5  # 5: rebuild threads an old settle closed under a newer message
_TERMINAL_KINDS = frozenset({"turn.settled", "turn.failed", "turn.cancelled", "turn.deferred"})
_REOPENED_KINDS = (*sorted(_TERMINAL_KINDS), "message.member", "room.assignment", "room.routed", "room.continued")

@dataclass(frozen=True)
class PolicySnapshot:
    """Bounded active policy input at one durable room-log cursor."""
    through_seq: int
    stopped_through_seq: int
    events: tuple[dict[str, Any], ...]
    watermarks: Mapping[tuple[str, str], int]

def _text(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping.get(key) or "")
PolicySnapshot.__module__ = 'gateway.hosted_room_policy_checkpoint'

MAX_STATUS_GRANT_TTL_SECONDS = 30 * 24 * 60 * 60
