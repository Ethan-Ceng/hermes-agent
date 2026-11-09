"""Shared room validation and exact wire values; no Native storage service."""
from __future__ import annotations
from hermes_db.domains.rooms.authority_rules import at_sequence
from hermes_db.domains.rooms import rules as _storage_shared_1
from hermes_db.domains.rooms.rules import identifier
import hashlib
import json
import re
MAX_TASKS = 128
MAX_RECEIPTS = 256
MAX_BYTES = 128 * 1024
MAX_STORE_BYTES = 4 * 1024 * 1024
MAX_STORE_ROWS = 512
PENDING_TABLE = "hosted_room_work_records_pending"
BLOCKED_DELIVERY_STATUSES = {"rejected", "needs_reauthorization", "invalid_ack", "unsupported_lineage", "invalid_work_evidence"}
LIMITATIONS = ["process_local_approvals_not_captured", "field_journals_not_captured",
               "external_effects_not_captured", "absent_record_is_not_non_admission", "not_execution_checkpoint"]
_PHASES = {"queued", "running", "indeterminate", "stopping", "deferred", "settled", "failed", "cancelled"}
_TASK_FIELDS = {
    "task_id", "thread_id", "turn_id", "source_event_seq", "payload_sha256", "member_id", "profile",
    "execution_generation", "cancel_generation", "phase", "settlement_id", "cancel_id"}
_RECEIPT_FIELDS = {
    "room_id", "home_install_id", "authority_gateway_id", "authority_epoch", "member_id", "target_install_id",
    "target_profile", "task_id", "execution_generation", "run_id", "session_id"}
_FIELDS = {"version", "room_id", "home_install_id", "authority", "roster_sha256", "history", "revision", "digest",
           "availability", "reason", "tasks", "receipts", "stop", "limitations"}

class WorkRecordError(ValueError):
    """Controlled invalid or unavailable work evidence."""

class InvalidStoredWorkRecord(WorkRecordError):
    """Retained bytes cannot be reused; commit their invalid disposition."""

class WorkRecordCapacityError(WorkRecordError):
    """The bounded evidence store is full."""

class WorkRecordPrefixError(WorkRecordError):
    """The matching canonical history prefix is not retained."""

def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def digest(value) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()

def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise WorkRecordError("work record fields are invalid")

def _integer(value, *, minimum=0):
    if type(value) is not int or not minimum <= value < 2**63:
        raise WorkRecordError("work record integer is invalid")

def _id(value):
    if identifier(value, label="record identity", error=WorkRecordError, max_chars=256) != value:
        raise WorkRecordError("work record identity is not canonical")

def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise WorkRecordError("work record digest is invalid")

def _validate_tasks(record, tasks):
    task_ids = set()
    for task in tasks:
        _fields(task, _TASK_FIELDS)
        for name in ("task_id", "thread_id", "turn_id", "member_id", "profile"):
            _id(task[name])
        for name in ("settlement_id", "cancel_id"):
            if task[name] is not None:
                _id(task[name])
        for name in ("execution_generation", "cancel_generation"):
            _integer(task[name])
        _integer(task["source_event_seq"], minimum=1)
        _sha(task["payload_sha256"])
        if task["source_event_seq"] > record["history"]["seq"] or task["phase"] not in _PHASES or task["task_id"] in task_ids:
            raise WorkRecordError("work record task conflicts")
        task_ids.add(task["task_id"])

def _validate_receipts(record, receipts, v2):
    receipt_ids = set()
    for receipt in receipts:
        _fields(receipt, _RECEIPT_FIELDS)
        for name in _RECEIPT_FIELDS - {"authority_epoch", "execution_generation"}:
            _id(receipt[name])
        _integer(receipt["execution_generation"], minimum=1)
        _integer(receipt["authority_epoch"], minimum=1)
        if (receipt["room_id"] != record["room_id"]
                or receipt["authority_gateway_id"] != receipt["home_install_id"]
                or (not v2 and (receipt["home_install_id"] != record["home_install_id"] or receipt["authority_epoch"] != 1))):
            raise WorkRecordError("work record receipt lineage conflicts")
        key = tuple(receipt[k] for k in sorted(_RECEIPT_FIELDS - {"run_id", "session_id"}))
        if key in receipt_ids:
            raise WorkRecordError("work record receipt is duplicated")
        receipt_ids.add(key)

def _validate_stop(record):
    _fields(record["stop"], {"closing", "revocation_complete", "seq", "cancel_id"})
    for key in ("closing", "revocation_complete"):
        if type(record["stop"][key]) is not bool:
            raise WorkRecordError("work record closing fact is invalid")
    _integer(record["stop"]["seq"])
    if record["stop"]["seq"] > record["history"]["seq"]:
        raise WorkRecordError("work record stop is beyond its prefix")
    if record["stop"]["cancel_id"] is not None:
        _id(record["stop"]["cancel_id"])

def _validate_availability(record):
    if record["availability"] not in {"available", "unavailable"} or record["reason"] not in {
        None, "task_store_missing", "unsupported_task", "bounds_exceeded"}:
        raise WorkRecordError("work record availability is invalid")
    if (record["availability"] == "available") != (record["reason"] is None):
        raise WorkRecordError("work record availability conflicts")
    tasks, receipts = record["tasks"], record["receipts"]
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS or not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        raise WorkRecordError("work record list exceeds its bound")
    if record["availability"] == "unavailable" and (tasks or receipts):
        raise WorkRecordError("unavailable work record must not appear complete")

def validate(record: dict) -> dict:
    v2 = isinstance(record, dict) and type(record.get("version")) is int and record["version"] == 2
    _fields(record, _FIELDS | {"lineage_sha256", "incompleteness"} if v2 else _FIELDS)
    if type(record["version"]) is not int or record["version"] not in {1, 2}:
        raise WorkRecordError("work record version is unsupported")
    _id(record["room_id"])
    _id(record["home_install_id"])
    _fields(record["authority"], {"gateway_id", "epoch"})
    _integer(record["authority"]["epoch"], minimum=1)
    if record["authority"]["gateway_id"] != record["home_install_id"] or (not v2 and record["authority"]["epoch"] != 1):
        raise WorkRecordError("work record authority is unsupported")
    if v2:
        _sha(record["lineage_sha256"])
        if record["incompleteness"] != ["prior_authority_work_unknown"]:
            raise WorkRecordError("work record incompleteness is required")
    _sha(record["roster_sha256"])
    _integer(record["revision"], minimum=1)
    _fields(record["history"], {"seq", "event_sha256"})
    _integer(record["history"]["seq"])
    _sha(record["history"]["event_sha256"])
    if record["limitations"] != LIMITATIONS:
        raise WorkRecordError("work record limitations are required")
    _validate_availability(record)
    _validate_tasks(record, record["tasks"])
    _validate_receipts(record, record["receipts"], v2)
    _validate_stop(record)
    _sha(record["digest"])
    if record["digest"] != digest({k: v for k, v in record.items() if k not in {"revision", "digest"}}):
        raise WorkRecordError("work record content digest conflicts")
    if len(encode(record).encode("utf-8")) > MAX_BYTES:
        raise WorkRecordError("work record exceeds its byte bound")
    return record

def _validate_roster(record, members):
    if roster_digest(members) != record["roster_sha256"]:
        raise WorkRecordError("work record roster conflicts")
    roster = {m.get("member_id", m.get("profile")): m for m in members}
    for task in record["tasks"]:
        if roster.get(task["member_id"], {}).get("profile") != task["profile"]:
            raise WorkRecordError("work record task target conflicts")
    for receipt in record["receipts"]:
        target = roster.get(receipt["member_id"], {}).get("target", {})
        if (target.get("kind") != "peer" or target.get("installation_id") != receipt["target_install_id"]
                or target.get("profile") != receipt["target_profile"]):
            raise WorkRecordError("work record receipt target conflicts")

def roster_digest(members):
    _, encoded = _storage_shared_1._validate_members(members)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()

def acknowledgement(record):
    """Exact passive ACK shape; never an admission or execution receipt."""
    ack = {"room_id": record["room_id"], "revision": record["revision"],
           "digest": record["digest"], "passive": True}
    if record["version"] == 2:
        ack.update(version=2, authority=record["authority"], lineage_sha256=record["lineage_sha256"])
    return ack
INVALID_TABLE = "hosted_room_work_records_invalid"

def retained_fields(table):
    fields = ['room_id', 'revision', 'digest', 'record_json']
    fields += ['source_table'] if table == INVALID_TABLE else ['producer_gateway_id', 'producer_epoch']
    if table in (PENDING_TABLE, INVALID_TABLE):
        fields += ['target_install_id', 'route_generation', 'status']
    return fields

def validate_stored(row):
    try:
        record = validate(json.loads(row['record_json']))
        if row['disposition'] == 'invalid' or scope(record) != (row['room_id'], row['producer_gateway_id'], row['producer_epoch']) or record['revision'] != row['revision'] or (record['digest'] != row['digest']):
            raise WorkRecordError('stored work metadata conflicts with record scope')
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise InvalidStoredWorkRecord('stored work evidence is invalid') from exc
    return record

def scope(record):
    return record["room_id"], record["authority"]["gateway_id"], record["authority"]["epoch"]

def validate_provenance(record, spans):
    # Execution generation remains an independent per-task counter.
    for task in record['tasks']:
        at_sequence(spans, task['source_event_seq'])
    for receipt in record['receipts']:
        if not any(s.gateway_id == receipt['home_install_id'] == receipt['authority_gateway_id'] and s.epoch == receipt['authority_epoch'] for s in spans):
            raise WorkRecordError('work record receipt has no original authority span')
WorkRecordError.__module__ = 'gateway.hosted_room_work_records'
InvalidStoredWorkRecord.__module__ = 'gateway.hosted_room_work_records'
WorkRecordCapacityError.__module__ = 'gateway.hosted_room_work_records'
WorkRecordPrefixError.__module__ = 'gateway.hosted_room_work_records'
