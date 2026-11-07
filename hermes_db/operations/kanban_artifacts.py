"""PG metadata with file preparation and cleanup outside database transactions."""

import contextlib
from pathlib import Path
import time
from uuid import uuid4

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageBusyError, UnknownCommitError
from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban_artifacts import attachments, blobs
from hermes_db.values import encode_text


def _blob_key(store, path):
    return and_(blobs.c.store_id == store.scope.require_store_id(), blobs.c.path == encode_text(path))


def lock_blob(conn, store, path):
    conn.execute(insert(blobs).values(store_id=store.scope.require_store_id(), path=encode_text(path)).on_conflict_do_nothing())
    token = conn.scalar(select(blobs.c.cleanup_token).where(_blob_key(store, path)).with_for_update())
    if token is not None:
        raise StorageBusyError("Attachment file cleanup is pending; retain the file and retry after reconciliation")


def insert_attachment(conn, store, task_id, *, filename, stored_path, content_type=None, size=0, uploaded_by=None, created_at=None):
    lock_blob(conn, store, stored_path)
    values = {key: encode_text(value) for key, value in dict(task_id=task_id, filename=filename,
              stored_path=stored_path, content_type=content_type, uploaded_by=uploaded_by).items()}
    attachment_id = conn.scalar(attachments.insert().values(**repo.owner(store), **values, size=int(size),
        created_at=int(time.time()) if created_at is None else created_at).returning(attachments.c.id))
    repo.event(conn, store, task_id, "attached", {"filename": filename, "size": int(size), "by": uploaded_by})
    return attachment_id


def add_attachment(store, task_id, *, filename, stored_path, content_type=None, size=0, uploaded_by=None):
    if not filename or not filename.strip():
        raise ValueError("attachment filename is required")
    if not stored_path or not stored_path.strip():
        raise ValueError("attachment stored_path is required")
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        attachment_id = insert_attachment(conn, store, task_id, filename=filename.strip(), stored_path=stored_path,
                                          content_type=content_type, size=size, uploaded_by=uploaded_by)
        return store.command_result(conn, attachment_id)


def store_attachment_bytes(store, task_id, filename, data, *, content_type=None, uploaded_by=None, board=None, max_bytes=None):
    from hermes_cli import kanban_db as kb
    if board is not None and kb._require_slug(board) != store.slug:
        raise ValueError("attachment Board must match its acquired Board resource")
    max_bytes = kb.KANBAN_ATTACHMENT_MAX_BYTES if max_bytes is None else max_bytes
    if len(data) > max_bytes:
        raise kb.AttachmentTooLarge(f"attachment exceeds {max_bytes // (1024 * 1024)} MB limit")
    safe_name = kb._safe_attachment_name(filename)
    # Unique file generations prevent cleanup of an old upload racing its replacement.
    directory = kb.task_attachments_dir(task_id, board=store.slug) / uuid4().hex
    directory.mkdir(parents=True)
    path = directory / safe_name
    try:
        path.write_bytes(data)
        return add_attachment(store, task_id, filename=safe_name, stored_path=str(path.resolve()),
                               content_type=content_type, size=len(data), uploaded_by=uploaded_by)
    except UnknownCommitError:
        # The metadata may be durable; destroying the file would destroy an acknowledged upload.
        raise
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
            directory.rmdir()
        raise


def _id(store, attachment_id):
    return and_(repo.scope(attachments, store), attachments.c.id == int(attachment_id))


def get_attachment(store, attachment_id):
    from hermes_cli.kanban_db import Attachment
    with store.read() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        return Attachment.from_row(repo.decode_record(row)) if row is not None else None


def list_attachments(store, task_id):
    from hermes_cli.kanban_db import Attachment
    with store.read() as conn:
        return [Attachment.from_row(repo.decode_record(row)) for row in conn.execute(select(attachments)
            .where(repo.key(store, task_id, attachments)).order_by(attachments.c.created_at, attachments.c.id)).mappings()]


def _retire_attachment(store, attachment_id):
    from hermes_cli.kanban_db import Attachment
    with store.write() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        if row is None:
            return None, None
        attachment = Attachment.from_row(repo.decode_record(row))
        lock_blob(conn, store, attachment.stored_path)
        conn.execute(delete(attachments).where(_id(store, attachment_id)))
        remaining = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == store.scope.require_store_id(),
            attachments.c.stored_path == encode_text(attachment.stored_path)).limit(1))
        token = uuid4().hex if remaining is None else None
        if token is not None:
            conn.execute(update(blobs).where(_blob_key(store, attachment.stored_path)).values(cleanup_token=token))
        repo.event(conn, store, attachment.task_id, "attachment_removed", {"filename": attachment.filename})
        return attachment, token


def delete_attachment(store, attachment_id):
    attachment, token = _retire_attachment(store, attachment_id)
    if token is not None:
        with contextlib.suppress(OSError):
            path = Path(attachment.stored_path)
            if path.is_file():
                path.unlink()
        # File cleanup owns the store/path fence even if its Board was retired meanwhile.
        with DomainResource.write(store) as conn:
            conn.execute(update(blobs).where(_blob_key(store, attachment.stored_path), blobs.c.cleanup_token == token)
                .values(cleanup_token=None))
    return attachment
