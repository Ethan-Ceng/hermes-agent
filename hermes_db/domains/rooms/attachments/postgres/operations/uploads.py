"""Atomic quota/dedup/reference changes on already prepared private content."""

from sqlalchemy import func, select, update
from gateway import hosted_room_attachments as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.domains.rooms.attachments.postgres.queries import attachments as repo
from hermes_db.tables.room_attachments import attachments, blobs


def validate_retry(row, fields):
    if any(row[key] != fields[key] for key in ("kind", "name", "mime", "size", "sha256")):
        raise native.AttachmentConflictError("upload_id was already used for different attachment content")


def _quota(conn, store, fields, limits):
    count, size = repo.totals(conn, store, room_id=fields["room_id"], live_only=True)
    if size + fields["size"] > limits["room_quota_bytes"]:
        raise native.AttachmentQuotaError("room attachment quota exceeded")
    if count >= limits["room_quota_count"]:
        raise native.AttachmentQuotaError("room attachment count quota exceeded")
    total_count, _ = repo.totals(conn, store)
    if total_count >= limits["gateway_quota_count"]:
        raise native.AttachmentQuotaError("gateway attachment count quota exceeded")
    count, size = repo.totals(conn, store, room_id=fields["room_id"], state="uploaded")
    if size + fields["size"] > native.MAX_ROOM_UNCOMMITTED_BYTES or count + 1 > native.MAX_ROOM_UNCOMMITTED_COUNT:
        raise native.AttachmentQuotaError("room uncommitted upload quota exceeded")


def put(store, *, fields, candidate_blob, now, limits):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        previous = repo.attachment(conn, store, room_id=fields["room_id"], upload_id=fields["upload_id"])
        if previous is not None:
            validate_retry(previous, fields)
            return previous, True
        _quota(conn, store, fields, limits)
        blob = repo.blob(conn, store, sha256=fields["sha256"])
        if blob is None:
            physical = conn.scalar(select(func.coalesce(func.sum(blobs.c.size), 0)).where(room_repo.scope(blobs, store)))
            if physical + fields["size"] > limits["gateway_quota_bytes"]:
                raise native.AttachmentQuotaError("gateway attachment quota exceeded")
            blob_id = candidate_blob
            room_repo.insert_row(conn, store, blobs, dict(blob_id=blob_id, sha256=fields["sha256"], size=fields["size"], ref_count=1, created_at=now))
        else:
            blob_id = blob["blob_id"]
            conn.execute(update(blobs).where(room_repo.key(blobs, store, dict(blob_id=blob_id))).values(ref_count=blobs.c.ref_count + 1))
        room_repo.insert_row(conn, store, attachments, dict(fields, blob_id=blob_id, event_id=None,
            recipient_member_ids_json="[]", viewer_access=0, state="uploaded", created_at=now, updated_at=now,
            expires_at=now + native.UNCOMMITTED_TTL_SECONDS))
        return repo.attachment(conn, store, fields["attachment_id"]), False


def find_upload(store, *, room_id, upload_id, now):
    with store.read() as conn:
        row = repo.attachment(conn, store, room_id=room_id, upload_id=upload_id)
        if row is None or row["state"] == "disbanded" or (row["expires_at"] is not None and row["expires_at"] <= now):
            return None
        return row
