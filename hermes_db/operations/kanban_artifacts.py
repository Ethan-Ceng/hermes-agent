"""PG metadata with file preparation and cleanup outside database transactions."""

import contextlib
from pathlib import Path
import time
from uuid import uuid4

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.errors import StorageBusyError, UnknownCommitError
from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban_artifacts import attachments, blobs
from hermes_db.core.values import encode_text


def _blob_key(store, path):
    return and_(blobs.c.store_id == store.scope.require_store_id(), blobs.c.path == encode_text(path))


def lock_blob(conn, store, path):
    conn.execute(insert(blobs).values(store_id=store.scope.require_store_id(), path=encode_text(path)).on_conflict_do_nothing())
    token = conn.scalar(select(blobs.c.cleanup_token).where(_blob_key(store, path)).with_for_update())
    if token is not None:
        raise StorageBusyError("Attachment file cleanup is pending; retain the file and retry after reconciliation")


def insert_attachment(conn, store, task_id, *, filename, stored_path, file_key, content_type=None, size=0, uploaded_by=None, created_at=None):
    from hermes_db.operations.kanban_file_jobs import guard_reference
    guard_reference(conn, store, file_key)
    lock_blob(conn, store, file_key)
    values = {key: encode_text(value) for key, value in dict(task_id=task_id, filename=filename,
              stored_path=stored_path, content_type=content_type, uploaded_by=uploaded_by).items()}
    attachment_id = conn.scalar(attachments.insert().values(**repo.owner(store), **values, path_key=encode_text(file_key), size=int(size),
        created_at=int(time.time()) if created_at is None else created_at).returning(attachments.c.id))
    repo.event(conn, store, task_id, "attached", {"filename": filename, "size": int(size), "by": uploaded_by})
    return attachment_id


def add_attachment(store, task_id, *, filename, stored_path, content_type=None, size=0, uploaded_by=None):
    _preflight_reference(store, stored_path)
    from hermes_db.operations.kanban_file_jobs import local_files_lock
    with local_files_lock(store.scope.profile_home):
        _preflight_reference(store, stored_path)
        return _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by)


def _preflight_reference(store, path):
    from hermes_db.operations.kanban_file_jobs import guard_reference
    from hermes_db.repositories.kanban_workspaces import canonical_path
    key = canonical_path(path)
    with store.read() as conn:
        guard_reference(conn, store, key)
        pending = list(conn.scalars(select(blobs.c.path).where(blobs.c.store_id == store.scope.require_store_id(),
            blobs.c.cleanup_token.is_not(None))))
    from hermes_db.core.values import decode_text
    if any(canonical_path(decode_text(raw)) == key for raw in pending):
        raise StorageBusyError("Attachment file cleanup is pending; retain the file and retry after reconciliation")


def _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by):
    if not filename or not filename.strip():
        raise ValueError("attachment filename is required")
    if not stored_path or not stored_path.strip():
        raise ValueError("attachment stored_path is required")
    from hermes_db.repositories.kanban_workspaces import canonical_path
    stored_path = str(Path(stored_path).expanduser().resolve())
    file_key = canonical_path(stored_path)
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        attachment_id = insert_attachment(conn, store, task_id, filename=filename.strip(), stored_path=stored_path, file_key=file_key,
                                          content_type=content_type, size=size, uploaded_by=uploaded_by)
        return store.command_result(conn, attachment_id)


def store_attachment_bytes(store, task_id, filename, data, *, content_type=None, uploaded_by=None, board=None, max_bytes=None):
    from hermes_db.operations.kanban_file_jobs import local_files_lock
    with local_files_lock(store.scope.profile_home):
        return _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes)


def _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes):
    from hermes_cli import kanban_db as kb
    if board is not None and kb._require_slug(board) != store.slug:
        raise ValueError("attachment Board must match its acquired Board resource")
    max_bytes = kb.KANBAN_ATTACHMENT_MAX_BYTES if max_bytes is None else max_bytes
    if len(data) > max_bytes:
        raise kb.AttachmentTooLarge(f"attachment exceeds {max_bytes // (1024 * 1024)} MB limit")
    safe_name = kb._safe_attachment_name(filename)
    # Unique file generations prevent cleanup of an old upload racing its replacement.
    from hermes_db.operations.kanban_attachment_cleanup import prepare_directory
    directory = prepare_directory(store, kb.task_attachments_dir(task_id, board=store.slug))
    path = directory / safe_name
    try:
        path.write_bytes(data)
        return _add_attachment(store, task_id, safe_name, str(path.resolve()), content_type, len(data), uploaded_by)
    except UnknownCommitError:
        # The metadata may be durable; destroying the file would destroy an acknowledged upload.
        raise
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
            from hermes_db.operations.kanban_attachment_cleanup import discard_empty_generation
            discard_empty_generation(store, directory)
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
    from hermes_db.repositories.kanban_workspaces import canonical_path
    captured = get_attachment(store, attachment_id)
    file_key = canonical_path(captured.stored_path) if captured is not None else None
    with store.write() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        if row is None:
            return None, None
        attachment = Attachment.from_row(repo.decode_record(row))
        if captured != attachment or row["path_key"] != encode_text(file_key):
            raise StorageBusyError("Attachment path changed or is unresolved; preserve its file for reconciliation")
        lock_blob(conn, store, file_key)
        conn.execute(delete(attachments).where(_id(store, attachment_id)))
        remaining = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == store.scope.require_store_id(),
            attachments.c.path_key == encode_text(file_key)).limit(1))
        unresolved = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == store.scope.require_store_id(),
            attachments.c.path_key.is_(None)).limit(1))
        token = uuid4().hex if remaining is None and unresolved is None else None
        if token is not None:
            conn.execute(update(blobs).where(_blob_key(store, file_key)).values(cleanup_token=token))
        repo.event(conn, store, attachment.task_id, "attachment_removed", {"filename": attachment.filename})
        return attachment, token


def delete_attachment(store, attachment_id):
    from hermes_db.operations.kanban_file_jobs import local_files_lock
    from hermes_db.operations.kanban_attachment_cleanup import finish
    with local_files_lock(store.scope.profile_home):
        attachment, token = _retire_attachment(store, attachment_id)
        if token is not None:
            from hermes_db.repositories.kanban_workspaces import canonical_path
            finish(store, attachment.stored_path, token, blob_path=canonical_path(attachment.stored_path))
    return attachment
