"""Authorization snapshots precede and follow byte I/O on PG attachment paths."""

import json
from sqlalchemy import select
from gateway import hosted_room_attachments as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.domains.rooms.attachments.postgres.queries import attachments as repo
from hermes_db.tables.rooms import rooms, retired


def viewer_room(conn, store, *, room_id, authority_gateway_id, authority_epoch):
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, room_id))).mappings().one_or_none()
    if (row is None or row["disbanded_at"] is not None
            or row["authority_gateway_id"] != authority_gateway_id or row["authority_epoch"] != authority_epoch):
        raise native.AttachmentNotFoundError("Group Chat viewer authority changed")


def owner_event(conn, store, room_id, event_id):
    event = room_repo.event(conn, store, room_id, event_id)
    return event if event is not None and event["kind"] in {"message.user", "message.member"} else None


def committed_row(conn, store, *, room_id, attachment_id, recipient_member_id, normalized_event, viewer, now):
    row = repo.attachment(conn, store, attachment_id, room_id=room_id)
    if row is None or row["state"] != "committed":
        raise native.AttachmentNotFoundError("attachment is not committed for this room")
    if row["expires_at"] is not None and row["expires_at"] <= now:
        raise native.AttachmentNotFoundError("attachment has expired")
    if normalized_event is not None and (row["event_id"] or "") != normalized_event:
        raise native.AttachmentNotFoundError("attachment is not owned by this room event")
    if row["viewer_access"]:
        event = owner_event(conn, store, room_id, row["event_id"] or "")
        payload = json.loads(event["payload_json"]) if event is not None else None
        manifest = {key: row[key] for key in ("attachment_id", "kind", "name", "size", "mime")}
        published = payload.get("attachments") if isinstance(payload, dict) else None
        if not isinstance(published, list) or manifest not in published:
            raise native.AttachmentNotFoundError("attachment is not published in this room")
        # A permanent tombstone remains authoritative after the room payload is pruned.
        unavailable = conn.scalar(select(retired.c.room_id).where(room_repo.scope(retired, store, room_id))) is not None
        if unavailable:
            raise native.AttachmentNotFoundError("Group Chat is unavailable to viewers")
    recipients = json.loads(row["recipient_member_ids_json"])
    if viewer:
        if row["viewer_access"] != 1:
            raise native.AttachmentNotFoundError("attachment is unavailable to Group Chat viewers")
    elif recipient_member_id not in recipients:
        raise native.AttachmentNotFoundError("attachment is unavailable to this recipient")
    return row


def select_committed(store, *, authority=None, **selection):
    with store.read() as conn:
        if authority is not None:
            viewer_room(conn, store, **authority)
        return committed_row(conn, store, **selection)
