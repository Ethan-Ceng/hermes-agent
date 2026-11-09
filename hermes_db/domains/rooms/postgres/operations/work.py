"""Passive evidence joins the fact transaction, never authorizes execution."""

import json
import logging

from sqlalchemy.exc import DBAPIError
from sqlalchemy import select
from gateway import hosted_room_work_records as native, hosted_room_work_lineage as lineage
from hermes_db.domains.rooms.postgres.operations import work_snapshot as snapshot
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, work as repo
from hermes_db.tables.room_work import source
from hermes_db.tables.rooms import rooms


def _record(content, revision):
    return {**content, "revision": revision, "digest": native.digest(content)}


def capture_locked(conn, store, *, room_id, local_gateway_id, through_seq=None):
    room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
    if room["authority_gateway_id"] != local_gateway_id or room["disbanded_at"] is not None:
        raise native.WorkRecordError("work record source is unavailable")
    if through_seq is not None and room["next_seq"] - 1 > through_seq:
        raise native.WorkRecordPrefixError("history delivery must precede work records")
    content, spans = snapshot.content(conn, store, room)
    previous = repo.read(conn, store, source, repo.record_key(source, store, content))
    previous_record = repo.validate_locked(conn, store, source, previous) if previous is not None else None
    revision = previous_record["revision"] + 1 if previous_record else 1
    record = _record(content, revision)
    if len(native.encode(record).encode("utf-8")) > native.MAX_BYTES:
        content.update(tasks=[], receipts=[], availability="unavailable", reason="bounds_exceeded")
        record = _record(content, revision)
    try:
        native.validate(record)
        native._validate_roster(record, json.loads(room["members_json"]))
        if spans is not None:
            lineage.validate_provenance(record, spans)
    except native.WorkRecordError:
        if content["reason"] is not None:
            raise
        content.update(tasks=[], receipts=[], availability="unavailable", reason="unsupported_task")
        record = native.validate(_record(content, revision))
    if previous_record is not None and previous_record["digest"] == record["digest"]:
        return previous_record
    repo.save(conn, store, source, record)
    return record


def capture(store, *, room_id, local_gateway_id, through_seq=None):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        try:
            return capture_locked(conn, store, room_id=room_id, local_gateway_id=local_gateway_id, through_seq=through_seq)
        except native.InvalidStoredWorkRecord:
            pass  # Classification commits before the controlled refusal is reported.
    raise native.InvalidStoredWorkRecord("stored work evidence is invalid")


def capture_transition_locked(conn, store, room_id):
    from gateway.hosted_rooms_common import IDENTIFIER_RE
    if not isinstance(room_id, str) or not IDENTIFIER_RE.fullmatch(room_id):
        return  # An opaque receipt with no canonical room cannot be a source snapshot.
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, room_id))).mappings().one_or_none()
    if row is None or row["disbanded_at"] is not None:
        return
    room = room_repo.decode(row)
    savepoint = conn.begin_nested()
    try:
        capture_locked(conn, store, room_id=room_id, local_gateway_id=room["authority_gateway_id"])
    except native.InvalidStoredWorkRecord:
        savepoint.commit()
        logging.getLogger(__name__).warning("Hosted work evidence invalid for room %s", room_id)
    except (native.WorkRecordError, DBAPIError):
        savepoint.rollback()
        logging.getLogger(__name__).warning("Hosted work evidence unavailable for room %s", room_id, exc_info=True)
    else:
        savepoint.commit()
