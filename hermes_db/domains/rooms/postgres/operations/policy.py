"""Cursor CAS, bounded snapshots and derived-cache rebuild transactions."""

from sqlalchemy import delete, func, select, update
from gateway import hosted_rooms, hosted_room_policy_checkpoint as native
from hermes_db.domains.rooms.postgres.operations.policy_projection import apply_event
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, policy as repo
from hermes_db.tables.room_policy import capacity, cursors, transcript_state, threads, active, watermarks, transcript


def initialize(store, requested):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.upsert(conn, store, capacity, dict(singleton=1, max_active_events=requested),
            lambda excluded: dict(max_active_events=func.greatest(capacity.c.max_active_events, excluded.max_active_events)))
        return conn.scalar(select(capacity.c.max_active_events).where(room_repo.scope(capacity, store), capacity.c.singleton == 1))


def ensure_cursor(store, room_id):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
        repo.insert_ignore(conn, store, cursors, dict(room_id=room_id, through_seq=0, stopped_through_seq=0, updated_at=0))
        version = conn.scalar(select(transcript_state.c.schema_version).where(room_repo.scope(transcript_state, store, room_id)))
        if version is None or version < native._TRANSCRIPT_SCHEMA_VERSION:
            for table in (active, threads, watermarks, transcript):
                conn.execute(delete(table).where(room_repo.scope(table, store, room_id)))
            conn.execute(update(cursors).where(room_repo.scope(cursors, store, room_id)).values(through_seq=0, stopped_through_seq=0))
            repo.upsert(conn, store, transcript_state, dict(room_id=room_id, schema_version=native._TRANSCRIPT_SCHEMA_VERSION),
                lambda excluded: dict(schema_version=excluded.schema_version))
        cursor = conn.scalar(select(cursors.c.through_seq).where(room_repo.scope(cursors, store, room_id)))
        if cursor >= room["next_seq"]:
            raise RuntimeError("room policy cursor is ahead of the durable log")
        return cursor


def apply_page(store, room_id, expected, rows, next_cursor):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
        current = conn.scalar(select(cursors.c.through_seq).where(room_repo.scope(cursors, store, room_id)).with_for_update())
        if current is None:
            raise RuntimeError("room policy cursor disappeared during replay")
        if current != expected:
            return current
        for event in rows:
            apply_event(conn, store, event)
        changed = conn.execute(update(cursors).where(room_repo.scope(cursors, store, room_id), cursors.c.through_seq == expected).values(
            through_seq=next_cursor, updated_at=float(rows[-1].get("created_at") or 0)))
        if changed.rowcount != 1:
            raise RuntimeError("room policy cursor disappeared during replay")
    return next_cursor


def snapshot(store, room_id, *, max_active, max_transcript):
    with store.read() as conn:
        cursor = conn.execute(select(cursors).where(room_repo.scope(cursors, store, room_id))).mappings().one_or_none()
        if cursor is None:
            raise hosted_rooms.RoomNotFoundError("hosted room checkpoint not found")
        thread = conn.execute(select(threads).where(room_repo.scope(threads, store, room_id), threads.c.completed == 0,
            threads.c.latest_user_seq > cursor["stopped_through_seq"]).order_by(threads.c.latest_user_seq, threads.c.thread_id).limit(1)).mappings().one_or_none()
        if thread is None:
            return native.PolicySnapshot(cursor["through_seq"], cursor["stopped_through_seq"], (), {})
        thread = room_repo.decode(thread)
        events = repo.discussion_events(conn, store, room_id=room_id, thread_id=thread["thread_id"],
            discussion_event_id=thread["discussion_event_id"], max_active=max_active, max_transcript=max_transcript,
            bound_error="active room policy projection exceeded its bound")
        rows = [room_repo.decode(row) for row in conn.execute(select(watermarks).where(room_repo.key(watermarks, store,
            dict(room_id=room_id, thread_id=thread["thread_id"])))).mappings()]
        return native.PolicySnapshot(cursor["through_seq"], cursor["stopped_through_seq"], tuple(events),
            {(thread["thread_id"], row["member_id"]): row["seen_through_seq"] for row in rows})


def compact_completed(store, room_id):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        completed = select(threads.c.discussion_event_id).where(room_repo.scope(threads, store, room_id), threads.c.completed == 1)
        conn.execute(delete(active).where(room_repo.scope(active, store, room_id), active.c.discussion_event_id.in_(completed)))
        conn.execute(delete(threads).where(room_repo.scope(threads, store, room_id), threads.c.completed == 1))
