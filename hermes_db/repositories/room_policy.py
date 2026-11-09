"""Typed projection inserts and bounded room-history reconstruction on Core."""

import json
from sqlalchemy import delete, func, select, union_all
from sqlalchemy.dialects.postgresql import insert
from gateway import hosted_rooms as native
from gateway import hosted_room_policy_checkpoint as policy
from hermes_db.repositories import rooms as room_repo
from hermes_db.tables.rooms import events
from hermes_db.tables.room_policy import active, transcript
from hermes_db.core.values import decode_text, encode_text


def insert_ignore(conn, store, table, fields):
    conn.execute(insert(table).values(store_id=store.scope.require_store_id(), **room_repo.values(table, fields)).on_conflict_do_nothing())


def upsert(conn, store, table, fields, changes):
    statement = insert(table).values(store_id=store.scope.require_store_id(), **room_repo.values(table, fields))
    conn.execute(statement.on_conflict_do_update(index_elements=list(table.primary_key.columns), set_=changes(statement.excluded)))


def event_values(row):
    return native._event_from_row(room_repo.decode(row))


def source_event(conn, store, room_id, seq):
    row = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq == seq)).mappings().one_or_none()
    return event_values(row) if row is not None else None


def store_active(conn, store, event, thread_id, discussion_id):
    insert_ignore(conn, store, active, dict(room_id=event["room_id"], thread_id=thread_id, discussion_event_id=discussion_id,
        seq=int(event["seq"]), event_json=policy.compact_json(dict(event)), kind=event["kind"]))


def store_transcript(conn, store, event, thread_id, settled_seq=None):
    key = room_repo.key(transcript, store, dict(room_id=event["room_id"], thread_id=thread_id))
    upsert(conn, store, transcript, dict(room_id=event["room_id"], thread_id=thread_id, seq=int(event["seq"]), kind=event["kind"], settled_seq=settled_seq),
        lambda excluded: dict(settled_seq=func.coalesce(excluded.settled_seq, transcript.c.settled_seq)))
    if event["kind"] in {"message.user", "message.member"}:
        cutoff = conn.scalar(select(transcript.c.seq).where(key, transcript.c.kind.in_(("message.user", "message.member"))).order_by(
            transcript.c.seq.desc()).offset(policy.MAX_THREAD_TRANSCRIPT_EVENTS - 1).limit(1))
        if cutoff is not None:
            conn.execute(delete(transcript).where(key, transcript.c.seq < cutoff))


def discussion_events(conn, store, *, room_id, thread_id, discussion_event_id, max_active, max_transcript, bound_error):
    active_rows = []
    for deferred, bound in ((False, max_active), (True, policy.MAX_ACTIVE_RETRY_RECEIPTS)):
        selected = select(active.c.event_json).where(room_repo.scope(active, store, room_id),
            active.c.discussion_event_id == encode_text(discussion_event_id), (active.c.kind == "turn.deferred") == deferred).order_by(active.c.seq).limit(bound + 1)
        rows = conn.execute(selected).scalars().all()
        if len(rows) > bound:
            raise RuntimeError(bound_error)
        active_rows.extend(json.loads(decode_text(row)) for row in rows)
    key = room_repo.key(transcript, store, dict(room_id=room_id, thread_id=thread_id))
    references = union_all(select(transcript.c.seq).where(key), select(transcript.c.settled_seq.label("seq")).where(
        key, transcript.c.settled_seq.is_not(None))).subquery()
    rows = conn.execute(select(events).join(references, events.c.seq == references.c.seq).where(room_repo.scope(events, store, room_id)).order_by(
        events.c.seq).limit(max_transcript + 1)).mappings().all()
    if len(rows) > max_transcript:
        raise RuntimeError("thread policy transcript exceeded its bound")
    merged = {int(event["seq"]): event for event in [*(event_values(row) for row in rows), *active_rows]}
    return [merged[seq] for seq in sorted(merged)]
