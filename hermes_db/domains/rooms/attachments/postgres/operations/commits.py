"""Immutable commitment and event retention share the scoped metadata writer."""

import json
from sqlalchemy import update
from gateway import hosted_room_attachments as native
from gateway.hosted_rooms import EventAttachmentConflictError
from hermes_db.domains.rooms.attachments.postgres.operations.reads import owner_event
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.domains.rooms.attachments.postgres.queries import attachments as repo
from hermes_db.tables.room_attachments import attachments


def validate_row(row, entry, *, room_id, event_id, recipients_json, viewer_access, now):
    if row is None or row["room_id"] != room_id:
        raise native.AttachmentNotFoundError("attachment is not uploaded for this room")
    if {key: row[key] for key in native._ATTACHMENT_FIELDS} != entry:
        raise native.AttachmentConflictError("attachment manifest metadata does not match the uploaded bytes")
    if row["expires_at"] is not None and row["expires_at"] <= now:
        raise native.AttachmentNotFoundError("attachment has expired")
    if row["state"] == "disbanded":
        raise native.AttachmentNotFoundError("attachment belongs to a disbanded room")
    if row["state"] == "committed" and ((row["event_id"] or "") != event_id
            or row["recipient_member_ids_json"] != recipients_json or bool(row["viewer_access"]) != bool(viewer_access)):
        raise native.AttachmentConflictError("attachment is already owned by a different room event")


def prepare(store, *, manifest, **scope):
    with store.read() as conn:
        rows = [repo.attachment(conn, store, entry["attachment_id"]) for entry in manifest]
        for row, entry in zip(rows, manifest):
            validate_row(row, entry, **scope)
        return rows


def commit(store, *, manifest, expires_at, **scope):
    transitioned = []
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        rows = [repo.attachment(conn, store, entry["attachment_id"]) for entry in manifest]
        for row, entry in zip(rows, manifest):
            validate_row(row, entry, **scope)
        for row in rows:
            if row["state"] == "uploaded":
                transitioned.append(row["attachment_id"])
                conn.execute(update(attachments).where(room_repo.key(attachments, store, dict(attachment_id=row["attachment_id"])),
                    attachments.c.state == "uploaded").values(event_id=scope["event_id"], recipient_member_ids_json=scope["recipients_json"].encode(),
                        viewer_access=int(bool(scope["viewer_access"])), state="committed", updated_at=scope["now"], expires_at=expires_at))
    return manifest, tuple(transitioned)


def abort(store, *, room_id, event_id, attachment_ids, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        event = owner_event(conn, store, room_id, event_id)
        published = {item.get("attachment_id") for item in json.loads(event["payload_json"]).get("attachments", [])
                     if isinstance(item, dict)} if event is not None else set()
        selected = [value for value in attachment_ids if value not in published]
        if not selected:
            return 0
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.event_id == event_id,
            attachments.c.state == "committed", attachments.c.attachment_id.in_(selected)).values(event_id=None,
                recipient_member_ids_json=b"[]", viewer_access=0, state="uploaded", updated_at=now, expires_at=now + native.UNCOMMITTED_TTL_SECONDS)).rowcount


def retain_event(store, *, room_id, event_id, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        if room_repo.event(conn, store, room_id, event_id) is None:
            raise native.AttachmentConflictError("attachment owner event is not durable in the room log")
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.event_id == event_id,
            attachments.c.state == "committed").values(expires_at=None, updated_at=now)).rowcount


def retain_message_attachments(conn, store, *, room_id, event_id, manifest, now):
    normalized = native.validate_manifest(manifest)
    if normalized != manifest:
        raise native.AttachmentError("published attachment metadata must be canonical")
    for entry in normalized:
        row = repo.attachment(conn, store, entry["attachment_id"])
        if (row is None or row["room_id"] != room_id or row["event_id"] != event_id or row["state"] != "committed"
                or row["viewer_access"] != 1 or (row["expires_at"] is not None and row["expires_at"] <= now)
                or any(row[key] != value for key, value in entry.items())):
            raise EventAttachmentConflictError("attachment commitment changed before event publication")
    if normalized:
        conn.execute(update(attachments).where(room_repo.scope(attachments, store), attachments.c.attachment_id.in_(
            [entry["attachment_id"] for entry in normalized])).values(expires_at=None, updated_at=now))
