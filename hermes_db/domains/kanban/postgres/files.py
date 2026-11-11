"""Kanban files workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
import time
from uuid import uuid4
from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.errors import StorageBusyError, UnknownCommitError, StorageConfigurationError
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban_artifacts import attachments, blobs
from hermes_db.core.values import encode_text, decode_text
from hermes_db.domains.resource import DomainResource
import os
from hermes_db.tables.kanban_commands import command_receipts
from hermes_db.tables.kanban import tasks, kanban_boards
from hermes_db.tables.kanban_workspaces import references
from hermes_db.tables.kanban_file_jobs import file_jobs as jobs, file_locks as locks

def _blob_key(store, path):
    return and_(blobs.c.store_id == store.scope.require_store_id(), blobs.c.path == encode_text(path))

def lock_blob(conn, store, path):
    conn.execute(insert(blobs).values(store_id=store.scope.require_store_id(), path=encode_text(path)).on_conflict_do_nothing())
    token = conn.scalar(select(blobs.c.cleanup_token).where(_blob_key(store, path)).with_for_update())
    if token is not None:
        raise StorageBusyError('Attachment file cleanup is pending; retain the file and retry after reconciliation')

def insert_attachment(conn, store, task_id, *, filename, stored_path, file_key, content_type=None, size=0, uploaded_by=None, created_at=None):
    from hermes_db.domains.kanban.postgres.files import guard_reference
    guard_reference(conn, store, file_key)
    lock_blob(conn, store, file_key)
    values = {key: encode_text(value) for key, value in dict(task_id=task_id, filename=filename, stored_path=stored_path, content_type=content_type, uploaded_by=uploaded_by).items()}
    attachment_id = conn.scalar(attachments.insert().values(**repo.owner(store), **values, path_key=encode_text(file_key), size=int(size), created_at=int(time.time()) if created_at is None else created_at).returning(attachments.c.id))
    repo.event(conn, store, task_id, 'attached', {'filename': filename, 'size': int(size), 'by': uploaded_by})
    return attachment_id






def _id(store, attachment_id):
    return and_(repo.scope(attachments, store), attachments.c.id == int(attachment_id))

def get_attachment(store, attachment_id):

    with store.read() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        return store.result_values.attachment(repo.decode_record(row)) if row is not None else None

def list_attachments(store, task_id):

    with store.read() as conn:
        return [store.result_values.attachment(repo.decode_record(row)) for row in conn.execute(select(attachments).where(repo.key(store, task_id, attachments)).order_by(attachments.c.created_at, attachments.c.id)).mappings()]














def _references(conn, store, roots):
    joined = and_(tasks.c.store_id == references.c.store_id, tasks.c.board_id == references.c.board_id, tasks.c.id == references.c.task_id)
    live = list(conn.scalars(select(references.c.path_key).join(tasks, joined).where(references.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in([b'done', b'archived', b'failed', b'cancelled']))))
    blobs = list(conn.scalars(select(attachments.c.path_key).where(attachments.c.store_id == store.scope.require_store_id())))
    unresolved = conn.scalar(select(tasks.c.id).outerjoin(references, joined).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.workspace_path.is_not(None), tasks.c.status.not_in([b'done', b'archived', b'failed', b'cancelled']), references.c.task_id.is_(None)).limit(1))
    if unresolved is not None:
        return 'unresolved workspace paths require reconciliation'
    if any(value is None for value in blobs):
        return 'unresolved attachment paths require reconciliation'
    if any(under_root(decode_text(value), root) for value in [*live, *blobs] for root in roots):
        return 'other Board tasks or attachments still reference this content'
    return None


ROOT_FIELDS = ('data_root', 'attachments_root', 'workspaces_root', 'logs_root')


def under_root(key, root):
    import unicodedata
    root_key = os.path.normcase(unicodedata.normalize('NFC', os.path.normpath(root)))
    return key == root_key or key.startswith(root_key + os.sep)

def guard_reference(conn, store, key):
    if key is None:
        return
    retired = conn.execute(select(*(jobs.c[name] for name in ROOT_FIELDS)).where(jobs.c.store_id == store.scope.require_store_id(), (jobs.c.action == 'delete') | (jobs.c.action == 'import') & (jobs.c.state != 'done'))).all()
    if any(under_root(key, decode_text(root)) for row in retired for root in row):
        raise StorageBusyError('Board content has been retired; use an active Board content root')

def lock_files(conn, store):
    conn.execute(insert(locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(locks.c.store_id == store.scope.require_store_id()).with_for_update()).one()

def job_key(store, board_id):
    return and_(jobs.c.store_id == store.scope.require_store_id(), jobs.c.board_id == board_id)

def require_settled_slug(conn, store, slug):
    pending = conn.scalar(select(jobs.c.board_id).where(jobs.c.store_id == store.scope.require_store_id(), jobs.c.slug == slug, jobs.c.owner_home == encode_text(str(store.scope.profile_home)), jobs.c.state == 'pending').limit(1))
    if pending is not None:
        raise StorageBusyError('Board file operation is pending; retry its retirement or reconcile before reusing the slug')


def record(conn, store, row, fields, *, archive):
    action = 'archive' if archive else 'delete'
    existing = conn.execute(select(jobs).where(job_key(store, row['board_id']))).mappings().one_or_none()
    if existing is not None:
        if existing['action'] == action:
            return
        allowed = {('import', 'archive'), ('import', 'delete'), ('archive', 'delete')}
        if existing['state'] != 'done' or (existing['action'], action) not in allowed or existing['stage_root'] is not None:
            raise StorageBusyError('Complete the existing Board file operation before changing its action')
        conn.execute(update(jobs).where(job_key(store, row['board_id'])).values(action=action, state='pending', created_at=int(time.time()), **{key: encode_text(value) for key, value in fields.items()}))
        return
    conn.execute(jobs.insert().values(store_id=store.scope.require_store_id(), board_id=row['board_id'], slug=row['slug'], action=action, created_at=int(time.time()), **{key: encode_text(value) for key, value in fields.items()}))



def set_job_state(store, board_id, state):
    with store.write() as conn:
        lock_files(conn, store)
        conn.execute(update(jobs).where(job_key(store, board_id)).values(state=state))

def pending_delete(store, slug):
    with store.read() as conn:
        return conn.scalar(select(jobs.c.board_id).where(jobs.c.store_id == store.scope.require_store_id(), jobs.c.slug == slug, jobs.c.action == 'delete', jobs.c.state != 'done', jobs.c.owner_home == encode_text(str(store.scope.profile_home))))


def retire_attachment(store, attachment_id, captured, file_key):
    with store.write() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        if row is None:
            return (None, None)
        attachment = store.result_values.attachment(repo.decode_record(row))
        if captured != attachment or row['path_key'] != encode_text(file_key):
            raise StorageBusyError('Attachment path changed or is unresolved; preserve its file for reconciliation')
        lock_blob(conn, store, file_key)
        conn.execute(delete(attachments).where(_id(store, attachment_id)))
        remaining = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == store.scope.require_store_id(), attachments.c.path_key == encode_text(file_key)).limit(1))
        unresolved = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == store.scope.require_store_id(), attachments.c.path_key.is_(None)).limit(1))
        token = uuid4().hex if remaining is None and unresolved is None else None
        if token is not None:
            conn.execute(update(blobs).where(_blob_key(store, file_key)).values(cleanup_token=token))
        repo.event(conn, store, attachment.task_id, 'attachment_removed', {'filename': attachment.filename})
        return (attachment, token)


def pending_blob_paths(store, key):
    with store.read() as conn:
        guard_reference(conn, store, key)
        pending = list(conn.scalars(select(blobs.c.path).where(blobs.c.store_id == store.scope.require_store_id(), blobs.c.cleanup_token.is_not(None))))
    return pending


def verify_retired_blob(resource, original, key, token):
    with DomainResource.write(resource) as conn:
        lock_files(conn, resource)
        held = conn.scalar(select(blobs.c.cleanup_token).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.path == encode_text(original)))
        live = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == resource.scope.require_store_id(), (attachments.c.path_key == encode_text(key)) | attachments.c.path_key.is_(None)).limit(1))
        if held != token:
            raise StorageBusyError('Attachment cleanup token changed; preserve its file')
        if live is not None:
            raise StorageBusyError('Retired attachment path still has a live or unresolved reference; preserve its file')


def clear_retired_blob(resource, original, token):
    with DomainResource.write(resource) as conn:
        conn.execute(update(blobs).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.path == encode_text(original), blobs.c.cleanup_token == token).values(cleanup_token=None))


def attachment_cleanup_snapshot(resource):
    with DomainResource.write(resource) as conn:
        lock_files(conn, resource)
    with resource.read() as conn:
        pending = list(conn.execute(select(blobs.c.path, blobs.c.cleanup_token).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.cleanup_token.is_not(None))))
        live = set(conn.scalars(select(attachments.c.path_key).where(attachments.c.store_id == resource.scope.require_store_id())))
    return pending, live


def attachment_boards(resource):
    with resource.read() as conn:
        boards = list(conn.execute(select(kanban_boards.c.board_id, kanban_boards.c.slug).where(kanban_boards.c.store_id == resource.scope.require_store_id())))
    return boards


def completed_upload_command(resource, owner, command):
    with resource.read() as conn:
        found = conn.scalar(select(command_receipts.c.command_id).where(command_receipts.c.store_id == owner['store_id'], command_receipts.c.board_id == owner['board_id'], command_receipts.c.command_id == command['command_id'], command_receipts.c.request_digest == command['request_digest']))
    return found


def retired_root_references(store, roots):
    with store.write() as conn:
        lock_files(conn, store)
        reason = _references(conn, store, roots)
    return reason


def read_job(store, board_id):
    with store.read() as conn:
        raw = conn.execute(select(jobs).where(job_key(store, board_id))).mappings().one()
        row = repo.decode_record(raw)
    return row


def import_stage_status(store, board_id):
    with store.read() as conn:
        row = conn.execute(select(jobs.c.action, jobs.c.state, jobs.c.stage_root).where(job_key(store, board_id))).first()
    return row
