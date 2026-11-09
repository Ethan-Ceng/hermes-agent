"""Bounded room-scoped evidence, never executable driver state or authority."""

from __future__ import annotations
from hermes_db.domains.rooms import driver_rules as _driver_values
from hermes_db.domains.rooms.work_rules import BLOCKED_DELIVERY_STATUSES, InvalidStoredWorkRecord, LIMITATIONS, MAX_BYTES, MAX_RECEIPTS, MAX_STORE_BYTES, MAX_STORE_ROWS, MAX_TASKS, PENDING_TABLE, WorkRecordCapacityError, WorkRecordError, WorkRecordPrefixError, _RECEIPT_FIELDS, _TASK_FIELDS, _validate_roster, acknowledgement, digest, encode, roster_digest, validate
from hermes_db.domains.rooms import rules as _storage_shared_1

import hashlib
import json
import re
import sqlite3

from gateway import hosted_rooms as rooms
from gateway import hosted_room_work_storage as storage
from hermes_db.domains.rooms.rules import identifier
from gateway.hosted_rooms_common import table_exists
from hermes_db.domains.rooms.api import room_operation

VERSION = 1
PERMISSION = "work_records"
SOURCE_TABLE = "hosted_room_work_records_source"
TARGET_TABLE = "hosted_room_work_records_target"
































def initialize(conn: sqlite3.Connection) -> None:
    storage.initialize(conn)


def _budget(conn, table, proposed):
    total_sql, count_sql = storage.usage_sql((SOURCE_TABLE, PENDING_TABLE, storage.INVALID_TABLE))
    total, count = conn.execute(f"SELECT {total_sql}, {count_sql}").fetchone()
    keys = ["room_id", "producer_gateway_id", "producer_epoch"]
    if table == PENDING_TABLE:
        keys.append("target_install_id")
    where = " AND ".join(f"{k}=?" for k in keys)
    old = conn.execute(f"SELECT {storage.row_size_sql(table)} FROM {table} WHERE {where}",
                       [proposed[k] for k in keys]).fetchone()
    size = conn.execute(f"SELECT {storage.row_size_sql(table)} FROM (SELECT "
                        + ",".join(f"? AS {k}" for k in proposed) + ")", tuple(proposed.values())).fetchone()[0]
    if total - (old[0] if old else 0) + size > MAX_STORE_BYTES or count - bool(old) + 1 > MAX_STORE_ROWS:
        raise WorkRecordCapacityError("work record storage is full")


def history_anchor(conn, table: str, room_id: str, seq: int) -> str:
    if seq == 0:
        return digest([])
    row = conn.execute(f"""SELECT seq,event_id,kind,actor_json,authority_epoch,payload_json,created_at
        FROM {table} WHERE room_id=? AND seq=?""", (room_id, seq)).fetchone()
    if row is None:
        raise WorkRecordPrefixError("work record history prefix is unavailable")
    return digest([row["seq"], row["event_id"], row["kind"], json.loads(row["actor_json"]),
                   row["authority_epoch"], json.loads(row["payload_json"]), float(row["created_at"])])


def _capture_tasks(conn, room_id):
    from gateway import hosted_room_driver as driver
    if not table_exists(conn, "hosted_room_driver_tasks"):
        return [], [], "task_store_missing"
    # Published terminal records already travel in canonical history. Keep
    # outstanding tasks and unacknowledged publications within this small slice.
    published = ""
    if table_exists(conn, "hosted_room_policy_publications"):
        published = """NOT EXISTS (SELECT 1 FROM hosted_room_policy_publications AS p
            WHERE p.room_id=t.room_id AND p.task_id=t.task_id AND p.kind IN ('turn.settled','turn.failed','turn.cancelled'))"""
    task_filter = f" AND (status NOT IN ('settled','failed','cancelled') OR {published})" if published else ""
    rows = conn.execute("""SELECT task_id,thread_id,turn_id,source_event_seq,payload_json,payload_digest,
        status,execution_generation,cancel_generation,settlement_id,cancel_id
        FROM hosted_room_driver_tasks AS t WHERE room_id=?""" + task_filter + " ORDER BY task_id LIMIT ?",
        (room_id, MAX_TASKS + 1)).fetchall()
    receipts = [dict(row) for row in conn.execute(
        f"SELECT {','.join(sorted(_RECEIPT_FIELDS))} FROM hosted_room_remote_runs AS t WHERE room_id=?"
        + (f" AND {published}" if published else "") + " ORDER BY task_id,execution_generation,member_id LIMIT ?",
        (room_id, MAX_RECEIPTS + 1))]
    if len(rows) > MAX_TASKS or len(receipts) > MAX_RECEIPTS:
        return [], [], "bounds_exceeded"
    tasks = []
    for row in rows:
        try:
            payload, encoded, payload_digest = _driver_values._task_payload(json.loads(row["payload_json"]))
        except (ValueError, driver.DriverStateError):
            return [], [], "unsupported_task"
        if payload_digest != row["payload_digest"] or encoded != row["payload_json"] or payload["source_event_seq"] != row["source_event_seq"]:
            return [], [], "unsupported_task"
        tasks.append({**{key: row[key] for key in _TASK_FIELDS - {"payload_sha256", "phase", "member_id", "profile"}},
                      "payload_sha256": payload_digest, "phase": row["status"], "profile": payload["target_profile"],
                      "member_id": payload.get("target_member_id", payload["target_profile"])})
    return tasks, receipts, None


def capture_transition_locked(conn, room_id):
    """Observe committed driver facts, without making evidence an execution gate.

    The caller's transaction owns both facts and evidence. A rejected evidence
    write rolls back only its savepoint; malformed retained bytes are classified
    in place, never replaced with a fabricated current snapshot.
    """
    import logging
    owner = conn.execute(
        "SELECT authority_gateway_id FROM hosted_rooms WHERE room_id=? AND disbanded_at IS NULL",
        (room_id,)).fetchone()
    if owner is None:
        return
    conn.execute("SAVEPOINT work_transition_capture")
    try:
        capture_locked(conn, room_id=room_id, local_gateway_id=owner[0])
    except InvalidStoredWorkRecord:
        logging.getLogger(__name__).warning("Hosted work evidence invalid for room %s", room_id)
    except (WorkRecordError, sqlite3.Error):
        conn.execute("ROLLBACK TO work_transition_capture")
        logging.getLogger(__name__).warning("Hosted work evidence unavailable for room %s", room_id, exc_info=True)
    finally:
        conn.execute("RELEASE work_transition_capture")


@room_operation("room_work")
def capture(db_path, *, room_id: str, local_gateway_id: str, through_seq: int | None = None) -> dict:
    """Commit a new revision only when one consistent source view changes."""
    with rooms._transaction(db_path, immediate=True) as conn:
        try:
            return capture_locked(conn, room_id=room_id, local_gateway_id=local_gateway_id, through_seq=through_seq)
        except InvalidStoredWorkRecord:
            pass  # Commit this capture's invalid disposition, not new evidence.
    raise InvalidStoredWorkRecord("stored work evidence is invalid")


def capture_locked(conn, *, room_id, local_gateway_id, through_seq=None):
    initialize(conn)
    room = conn.execute("SELECT * FROM hosted_rooms WHERE room_id=?", (room_id,)).fetchone()
    if (room is None or room["authority_gateway_id"] != local_gateway_id or room["disbanded_at"] is not None):
        raise WorkRecordError("work record source is unavailable")
    seq = room["next_seq"] - 1
    if through_seq is not None and seq > through_seq:
        raise WorkRecordPrefixError("history delivery must precede work records")
    tasks, receipts, reason = _capture_tasks(conn, room_id)
    fence = None  # This runtime has no durable peer revocation completion proof.
    stop = conn.execute("""SELECT seq,payload_json FROM hosted_room_events
        WHERE room_id=? AND kind='room.stop_requested' ORDER BY seq DESC LIMIT 1""", (room_id,)).fetchone()
    content = {
        "version": 1 if room["authority_epoch"] == 1 else 2, "room_id": room_id, "home_install_id": local_gateway_id,
        "authority": {"gateway_id": local_gateway_id, "epoch": room["authority_epoch"]},
        "roster_sha256": roster_digest(json.loads(room["members_json"])),
        "history": {"seq": seq, "event_sha256": history_anchor(conn, "hosted_room_events", room_id, seq)},
        "availability": "unavailable" if reason else "available", "reason": reason,
        "tasks": tasks, "receipts": receipts, "limitations": LIMITATIONS,
        "stop": {"closing": fence is not None, "revocation_complete": fence is not None and fence[0] is not None,
                 "seq": stop["seq"] if stop else 0, "cancel_id": json.loads(stop["payload_json"]).get("cancel_id") if stop else None},
    }
    spans = None
    if content["version"] == 2:
        from gateway import hosted_room_work_lineage as lineage
        spans, content["lineage_sha256"] = lineage.source_prefix_locked(conn, room_id, content["authority"], seq)
        content["incompleteness"] = ["prior_authority_work_unknown"]
    previous = conn.execute(f"SELECT * FROM {SOURCE_TABLE} WHERE room_id=? AND producer_gateway_id=? AND producer_epoch=?",
                            storage.scope(content)).fetchone()
    previous_record = storage.validate_stored_locked(conn, SOURCE_TABLE, previous) if previous is not None else None
    revision = previous_record["revision"] + 1 if previous_record else 1
    record = {**content, "revision": revision, "digest": digest(content)}
    if len(encode(record).encode("utf-8")) > MAX_BYTES:
        content.update(tasks=[], receipts=[], availability="unavailable", reason="bounds_exceeded")
        record = {**content, "revision": revision, "digest": digest(content)}
    try:
        validate(record)
        _validate_roster(record, json.loads(room["members_json"]))
        if spans is not None:
            lineage.validate_provenance(record, spans)
    except WorkRecordError:
        if reason is not None:
            raise
        content.update(tasks=[], receipts=[], availability="unavailable", reason="unsupported_task")
        record = validate({**content, "revision": revision, "digest": digest(content)})
    if previous_record is not None and previous_record["digest"] == record["digest"]:
        return previous_record
    storage.save_locked(conn, SOURCE_TABLE, record)
    return record




def prepare_delivery_locked(conn, *, room_id, target_install_id, route_generation, local_gateway_id, through_seq):
    """Freeze a source view now; expose it only after its history is acknowledged."""
    initialize(conn)
    current = conn.execute("SELECT authority_gateway_id,authority_epoch FROM hosted_rooms WHERE room_id=?", (room_id,)).fetchone()
    if current is None or current["authority_gateway_id"] != local_gateway_id:
        raise WorkRecordError("work record source is unavailable")
    key = (room_id, current["authority_gateway_id"], current["authority_epoch"], target_install_id)
    old = conn.execute(f"SELECT * FROM {PENDING_TABLE} WHERE room_id=? AND producer_gateway_id=? AND producer_epoch=? AND target_install_id=?", key).fetchone()
    old_record = storage.validate_stored_locked(conn, PENDING_TABLE, old) if old is not None else None
    if old is not None and old["disposition"] != "current":
        raise WorkRecordError("pending work record is not current")
    if old is not None and old["status"] != "acked":
        if old["route_generation"] == route_generation and old["status"] in BLOCKED_DELIVERY_STATUSES:
            return None
        record = old_record
        current = conn.execute("SELECT authority_gateway_id,authority_epoch,members_json FROM hosted_rooms WHERE room_id=?", (room_id,)).fetchone()
        if (current is None or record["home_install_id"] != local_gateway_id
                or record["authority"] != {"gateway_id": current["authority_gateway_id"], "epoch": current["authority_epoch"]}
                or record["roster_sha256"] != roster_digest(json.loads(current["members_json"]))):
            raise WorkRecordError("pending work record source changed")
    else:
        record = capture_locked(conn, room_id=room_id, local_gateway_id=local_gateway_id)
        if old is not None and (old["revision"], old["digest"]) == (record["revision"], record["digest"]):
            return None
    if old is not None and old["status"] != "acked":
        # A legitimate migrated JSON spelling is still immutable pending bytes.
        conn.execute(f"""UPDATE {PENDING_TABLE} SET route_generation=?,status='pending'
            WHERE room_id=? AND producer_gateway_id=? AND producer_epoch=? AND target_install_id=?
            AND disposition='current'""", (route_generation, *key))
    else:
        storage.save_locked(conn, PENDING_TABLE, record, target_install_id=target_install_id, route_generation=route_generation)
    # Persist the anchor even while history is behind. Recapturing the moving
    # source tip on each attempt can otherwise starve a busy group indefinitely.
    return record if record["history"]["seq"] <= through_seq else None


def delivery_status_locked(conn, *, room_id, target_install_id, route_generation, record, status):
    initialize(conn)
    row = conn.execute(f"SELECT * FROM {PENDING_TABLE} WHERE room_id=? AND target_install_id=? "
                       "AND producer_gateway_id=? AND producer_epoch=? AND disposition='current'",
                       (room_id, target_install_id, record["authority"]["gateway_id"], record["authority"]["epoch"])).fetchone()
    if row is None:
        return False
    try:
        if storage.validate_stored_locked(conn, PENDING_TABLE, row) != record:
            return False
    except InvalidStoredWorkRecord:
        return False
    return conn.execute(f"""UPDATE {PENDING_TABLE} SET status=? WHERE room_id=? AND target_install_id=?
        AND route_generation=? AND revision=? AND digest=? AND producer_gateway_id=? AND producer_epoch=?
        AND disposition='current'""",
        (status, room_id, target_install_id, route_generation, record["revision"], record["digest"],
         record["authority"]["gateway_id"], record["authority"]["epoch"])).rowcount == 1







def acknowledge_locked(conn, *, room_id, target_install_id, route_generation, record, ack):
    if encode(ack) != encode(acknowledgement(record)):
        return False
    return delivery_status_locked(conn, room_id=room_id, target_install_id=target_install_id,
                                  route_generation=route_generation, record=record, status="acked")


@room_operation("room_work_delivery")
def prepare_delivery(db_path, **params):
    return _passive_write(db_path, prepare_delivery_locked, params)


@room_operation("room_work_delivery")
def delivery_status(db_path, **params):
    return _passive_write(db_path, delivery_status_locked, params)


@room_operation("room_work_delivery")
def acknowledge(db_path, **params):
    return _passive_write(db_path, acknowledge_locked, params)


def _passive_write(db_path, operation, params):
    with rooms._transaction(db_path, immediate=True) as conn:
        try:
            return operation(conn, **params)
        except InvalidStoredWorkRecord:
            pass
    raise InvalidStoredWorkRecord("stored work evidence is invalid")
