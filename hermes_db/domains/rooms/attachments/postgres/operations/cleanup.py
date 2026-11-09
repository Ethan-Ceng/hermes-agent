"""Retire references and queue exact file ids before any filesystem deletion."""

from collections import Counter
import json
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from gateway import hosted_room_attachments as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.domains.rooms.attachments.postgres.queries import attachments as repo
from hermes_db.tables.room_attachments import attachments, blobs, cleanup
from hermes_db.tables.rooms import rooms, retired, events


def reconcile(store, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        joined = attachments.join(events, (events.c.store_id == attachments.c.store_id) & (events.c.room_id == attachments.c.room_id)
            & (events.c.event_id == func.convert_to(attachments.c.event_id, "UTF8")))
        rows = conn.execute(select(attachments.c.attachment_id, events.c.payload_json).select_from(joined).where(
            room_repo.scope(attachments, store), attachments.c.state == "committed", attachments.c.expires_at.is_not(None))).mappings()
        changed = 0
        for row in rows:
            try:
                payload = json.loads(bytes(row["payload_json"]))
                ids = {str(item.get("attachment_id") or "") for item in payload.get("attachments", []) if isinstance(item, dict)}
            except (ValueError, TypeError, AttributeError, RecursionError):
                continue
            if row["attachment_id"] in ids:
                changed += conn.execute(update(attachments).where(room_repo.key(attachments, store, dict(attachment_id=row["attachment_id"])),
                    attachments.c.state == "committed").values(expires_at=None, updated_at=now)).rowcount
        return changed


def mark_disbanded(store, room_id, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.state != "disbanded").values(
            state="disbanded", updated_at=now, expires_at=now + native.DISBANDED_GRACE_SECONDS)).rowcount


def prune(store, *, now, namespace):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room_rows = conn.execute(select(rooms.c.room_id, rooms.c.disbanded_at).where(room_repo.scope(rooms, store), rooms.c.disbanded_at.is_not(None)))
        tombstones = dict(room_rows.all())
        tombstones.update(dict(conn.execute(select(retired.c.room_id, retired.c.retired_at).where(room_repo.scope(retired, store))).all()))
        for room_id, timestamp in tombstones.items():
            conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.state == "committed").values(
                state="disbanded", updated_at=now, expires_at=timestamp + native.DISBANDED_GRACE_SECONDS))
        expired = room_repo.scope(attachments, store) & attachments.c.expires_at.is_not(None) & (attachments.c.expires_at <= now)
        rows = conn.execute(select(attachments.c.attachment_id, attachments.c.blob_id).where(expired)).mappings().all()
        released = Counter(row["blob_id"] for row in rows)
        conn.execute(delete(attachments).where(expired))
        for blob_id, count in released.items():
            row = repo.blob(conn, store, blob_id=blob_id)
            if row is None:
                continue
            key = room_repo.key(blobs, store, dict(blob_id=blob_id))
            if row["ref_count"] > count:
                conn.execute(update(blobs).where(key).values(ref_count=blobs.c.ref_count - count))
            else:
                conn.execute(delete(blobs).where(key))
                conn.execute(insert(cleanup).values(store_id=store.scope.require_store_id(), blob_id=blob_id,
                    namespace=namespace, created_at=now).on_conflict_do_nothing())
        return len(rows)


def pending_jobs(store, namespace):
    with store.read() as conn:
        return list(conn.execute(select(cleanup.c.blob_id).where(room_repo.scope(cleanup, store), cleanup.c.namespace == namespace)).scalars())


def complete_job(store, namespace, blob_id):
    with store.write() as conn:
        conn.execute(delete(cleanup).where(room_repo.key(cleanup, store, dict(namespace=namespace, blob_id=blob_id))))


def live_blobs(store):
    # A lost connection can leave COMMIT resolving on the server. Taking this
    # store lock waits for that outcome before the caller sweeps files off-conn.
    with store.write() as conn:
        room_repo.lock_store(conn, store)
    # Start the snapshot after the fence transaction ended, including when the
    # server's writer default is repeatable-read. The caller still owns the
    # file gate, so no new publisher can appear between this read and its sweep.
    with store.read() as conn:
        return set(conn.execute(select(blobs.c.blob_id).where(room_repo.scope(blobs, store))).scalars())
