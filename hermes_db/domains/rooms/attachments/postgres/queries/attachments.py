"""Scoped attachment rows and quota snapshots, never filesystem operations."""

import secrets
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.room_attachments import attachments, blobs, roots


def namespace(store, now):
    with store.read() as conn:
        value = conn.scalar(select(roots.c.namespace).where(repo.scope(roots, store)))
    if value is not None:
        return value
    candidate = secrets.token_hex(16)
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(insert(roots).values(store_id=store.scope.require_store_id(), namespace=candidate, created_at=now).on_conflict_do_nothing())
        return conn.scalar(select(roots.c.namespace).where(repo.scope(roots, store)))


def attachment(conn, store, attachment_id=None, *, room_id=None, upload_id=None):
    fields = {key: value for key, value in dict(attachment_id=attachment_id, room_id=room_id, upload_id=upload_id).items() if value is not None}
    row = conn.execute(select(attachments).where(repo.key(attachments, store, fields))).mappings().one_or_none()
    return repo.record(row) if row is not None else None


def blob(conn, store, *, sha256=None, blob_id=None):
    fields = {key: value for key, value in dict(sha256=sha256, blob_id=blob_id).items() if value is not None}
    row = conn.execute(select(blobs).where(repo.key(blobs, store, fields))).mappings().one_or_none()
    return repo.record(row) if row is not None else None


def totals(conn, store, *, room_id=None, state=None, live_only=False):
    statement = select(func.count(), func.coalesce(func.sum(attachments.c.size), 0)).where(repo.scope(attachments, store, room_id))
    if state is not None:
        statement = statement.where(attachments.c.state == state)
    if live_only:
        statement = statement.where(attachments.c.state != "disbanded")
    count, size = conn.execute(statement).one()
    return int(count), int(size)


def stats(store, room_id):
    with store.read() as conn:
        count, size = totals(conn, store, room_id=room_id)
        blob_count, physical = conn.execute(select(func.count(), func.coalesce(func.sum(blobs.c.size), 0)).where(repo.scope(blobs, store))).one()
        return dict(attachments=count, logical_bytes=size, blobs=int(blob_count), physical_bytes=int(physical))
