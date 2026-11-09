"""Kanban files workflow; original connection, fence and off-connection effect boundaries are preserved."""
import contextlib
from pathlib import Path
import time
from uuid import uuid4
from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.errors import StorageBusyError, UnknownCommitError, StorageConfigurationError
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban_artifacts import attachments, blobs
from hermes_db.core.values import encode_text, decode_text
import json
import re
from hermes_db.core.resource import DomainResource
from contextlib import contextmanager
import os
from hermes_db.tables.kanban_commands import command_receipts
import shutil
from hermes_db.tables.kanban import tasks
from hermes_db.tables.kanban_workspaces import references
from hermes_db.domains.kanban.routing.files import BoardFiles, _path, content_root
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

def add_attachment(store, task_id, *, filename, stored_path, content_type=None, size=0, uploaded_by=None):
    _preflight_reference(store, stored_path)
    from hermes_db.domains.kanban.postgres.files import local_files_lock
    with local_files_lock(store.scope.profile_home):
        _preflight_reference(store, stored_path)
        return _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by)

def _preflight_reference(store, path):
    from hermes_db.domains.kanban.postgres.files import guard_reference
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    key = canonical_path(path)
    with store.read() as conn:
        guard_reference(conn, store, key)
        pending = list(conn.scalars(select(blobs.c.path).where(blobs.c.store_id == store.scope.require_store_id(), blobs.c.cleanup_token.is_not(None))))
    from hermes_db.core.values import decode_text
    if any(canonical_path(decode_text(raw)) == key for raw in pending):
        raise StorageBusyError('Attachment file cleanup is pending; retain the file and retry after reconciliation')

def _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by):
    if not filename or not filename.strip():
        raise ValueError('attachment filename is required')
    if not stored_path or not stored_path.strip():
        raise ValueError('attachment stored_path is required')
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    stored_path = str(Path(stored_path).expanduser().resolve())
    file_key = canonical_path(stored_path)
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        attachment_id = insert_attachment(conn, store, task_id, filename=filename.strip(), stored_path=stored_path, file_key=file_key, content_type=content_type, size=size, uploaded_by=uploaded_by)
        return store.command_result(conn, attachment_id)

def store_attachment_bytes(store, task_id, filename, data, *, content_type=None, uploaded_by=None, board=None, max_bytes=None):
    from hermes_db.domains.kanban.postgres.files import local_files_lock
    with local_files_lock(store.scope.profile_home):
        return _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes)

def _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes):
    from hermes_cli import kanban_db as kb
    if board is not None and kb._require_slug(board) != store.slug:
        raise ValueError('attachment Board must match its acquired Board resource')
    max_bytes = kb.KANBAN_ATTACHMENT_MAX_BYTES if max_bytes is None else max_bytes
    if len(data) > max_bytes:
        raise kb.AttachmentTooLarge(f'attachment exceeds {max_bytes // (1024 * 1024)} MB limit')
    safe_name = kb._safe_attachment_name(filename)
    from hermes_db.domains.kanban.postgres.files import prepare_directory
    directory = prepare_directory(store, kb.task_attachments_dir(task_id, board=store.slug))
    path = directory / safe_name
    try:
        path.write_bytes(data)
        return _add_attachment(store, task_id, safe_name, str(path.resolve()), content_type, len(data), uploaded_by)
    except UnknownCommitError:
        raise
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
            from hermes_db.domains.kanban.postgres.files import discard_empty_generation
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
        return [Attachment.from_row(repo.decode_record(row)) for row in conn.execute(select(attachments).where(repo.key(store, task_id, attachments)).order_by(attachments.c.created_at, attachments.c.id)).mappings()]

def _retire_attachment(store, attachment_id):
    from hermes_cli.kanban_db import Attachment
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    captured = get_attachment(store, attachment_id)
    file_key = canonical_path(captured.stored_path) if captured is not None else None
    with store.write() as conn:
        row = conn.execute(select(attachments).where(_id(store, attachment_id))).mappings().one_or_none()
        if row is None:
            return (None, None)
        attachment = Attachment.from_row(repo.decode_record(row))
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

def delete_attachment(store, attachment_id):
    from hermes_db.domains.kanban.postgres.files import local_files_lock
    from hermes_db.domains.kanban.postgres.files import finish
    with local_files_lock(store.scope.profile_home):
        attachment, token = _retire_attachment(store, attachment_id)
        if token is not None:
            from hermes_db.domains.kanban.postgres.workspaces import canonical_path
            finish(store, attachment.stored_path, token, blob_path=canonical_path(attachment.stored_path))
    return attachment

def _owner(resource):
    from hermes_db.integration.transfer.move_values import resource_key
    return dict(home=str(resource.scope.profile_home), store_id=resource.scope.require_store_id(), target=resource_key(resource._transactions))

def prepare_directory(resource, parent):
    from utils import atomic_json_write
    directory = Path(parent) / uuid4().hex
    if directory.resolve() != directory:
        raise StorageConfigurationError('Attachment preparation directory is redirected')
    directory.mkdir(parents=True)
    atomic_json_write(directory / '.owner.json', _owner(resource), mode=384)
    return directory

def discard_empty_generation(resource, directory):
    marker = directory / '.owner.json'
    if directory.resolve() == directory and marker.is_file() and (not marker.is_symlink()) and (json.loads(marker.read_text(encoding='utf-8-sig')) == _owner(resource)) and (set(directory.iterdir()) == {marker}):
        marker.unlink()
        directory.rmdir()

def discard_copies(resource, staged):
    from hermes_cli import kanban_db as kb
    kb._discard_staged_copies(staged, staged[0].parent)
    discard_empty_generation(resource, staged[0].parent)

def finish(resource, path, token, *, blob_path=None):
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    original = str(path) if blob_path is None else blob_path
    path = Path(path)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise StorageConfigurationError('Attachment cleanup path is relative or redirected; preserve its file')
    path = path.resolve()
    key = canonical_path(path)
    with DomainResource.write(resource) as conn:
        lock_files(conn, resource)
        held = conn.scalar(select(blobs.c.cleanup_token).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.path == encode_text(original)))
        live = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == resource.scope.require_store_id(), (attachments.c.path_key == encode_text(key)) | attachments.c.path_key.is_(None)).limit(1))
        if held != token:
            raise StorageBusyError('Attachment cleanup token changed; preserve its file')
        if live is not None:
            raise StorageBusyError('Retired attachment path still has a live or unresolved reference; preserve its file')
    if path.is_dir():
        raise StorageConfigurationError('Attachment cleanup expected a file')
    path.unlink(missing_ok=True)
    with DomainResource.write(resource) as conn:
        conn.execute(update(blobs).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.path == encode_text(original), blobs.c.cleanup_token == token).values(cleanup_token=None))

def reconcile(resource):
    with local_files_lock(resource.scope.profile_home):
        with DomainResource.write(resource) as conn:
            lock_files(conn, resource)
        with resource.read() as conn:
            pending = list(conn.execute(select(blobs.c.path, blobs.c.cleanup_token).where(blobs.c.store_id == resource.scope.require_store_id(), blobs.c.cleanup_token.is_not(None))))
            live = set(conn.scalars(select(attachments.c.path_key).where(attachments.c.store_id == resource.scope.require_store_id())))
        if None in live:
            raise StorageBusyError('Unresolved attachment paths require reconciliation before file cleanup')
        for raw, token in pending:
            finish(resource, decode_text(raw), token)
        _orphans(resource, live)

def _orphans(resource, live):
    from hermes_db.domains.kanban.routing.files import BoardFiles, _path
    from hermes_db.tables.kanban import kanban_boards
    with resource.read() as conn:
        boards = list(conn.execute(select(kanban_boards.c.board_id, kanban_boards.c.slug).where(kanban_boards.c.store_id == resource.scope.require_store_id())))
    owner = _owner(resource)
    for board_id, slug in boards:
        root = _path(BoardFiles(resource.scope.profile_home, board_id, slug), 'HERMES_KANBAN_ATTACHMENTS_ROOT', 'attachments')
        for marker in root.glob('*/*/.owner.json'):
            _sweep_generation(marker, root, owner, live)

def _sweep_generation(marker, root, owner, live):
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    directory = marker.parent
    if not re.fullmatch('[0-9a-f]{32}', directory.name):
        return
    if directory.resolve() != directory or marker.is_symlink() or (not directory.is_relative_to(root)):
        raise StorageConfigurationError('Attachment preparation generation is redirected')
    if json.loads(marker.read_text(encoding='utf-8-sig')) != owner:
        return
    retained = False
    for path in directory.iterdir():
        if path == marker:
            continue
        if encode_text(canonical_path(path)) in live:
            retained = True
        elif path.is_file() and (not path.is_symlink()):
            path.unlink()
        else:
            raise StorageConfigurationError('Unexpected content in private attachment generation')
    if not retained:
        marker.unlink()
        directory.rmdir()

@contextmanager
def _gate(root):
    from pm.filesystem import lock_path, unlock_fd
    descriptor = lock_path(root / '.lock', timeout=1, create_dir=False)
    if descriptor is None:
        raise StorageBusyError('Worker upload stage is busy')
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)

def _completed(resource, manifest, root):
    from hermes_db.integration.transfer.move_values import resource_key
    marker = root / 'command.json'
    owner = manifest['owner']
    if owner['store_id'] != resource.scope.require_store_id() or manifest.get('board_target') != resource_key(resource._transactions) or Path(owner['profile_home']).resolve() != resource.scope.profile_home:
        return False
    if marker.is_file() and (not marker.is_symlink()):
        command = json.loads(marker.read_text(encoding='utf-8'))
        with resource.read() as conn:
            found = conn.scalar(select(command_receipts.c.command_id).where(command_receipts.c.store_id == owner['store_id'], command_receipts.c.board_id == owner['board_id'], command_receipts.c.command_id == command['command_id'], command_receipts.c.request_digest == command['request_digest']))
        if found is not None:
            return True
    from hermes_db.integration.observations import terminal_execution
    return terminal_execution(manifest['session_store'], manifest['execution_id'], manifest['generation'])

def reclaim(resource):
    base = resource.scope.profile_home / 'kanban' / 'uploads'
    if not base.is_dir():
        return 0
    removed = 0
    for root in base.glob('*/*'):
        if not re.fullmatch('[0-9a-f]{64}', root.parent.name) or not re.fullmatch('[0-9a-f]{32}', root.name):
            continue
        if root.resolve() != root or not root.is_relative_to(base):
            raise StorageConfigurationError('Upload cleanup directory is redirected')
        with _gate(root):
            path = root / 'manifest.json'
            if path.is_symlink():
                raise StorageConfigurationError('Upload cleanup manifest is redirected')
            if not path.is_file():
                continue
            manifest = json.loads(path.read_text(encoding='utf-8-sig'))
            if not _completed(resource, manifest, root):
                continue
            from utils import atomic_write_bytes
            atomic_write_bytes(root / '.reclaimed', b'complete', mode=384, fsync_dir=True)
            for chunk in root.glob('*.part'):
                if re.fullmatch('\\d{6}\\.part', chunk.name):
                    chunk.unlink()
                    removed += 1
    return removed

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

def _remove_directory(path, *, board_id=None, parent=None):
    path = Path(path)
    resolved = path.resolve()
    if not path.is_absolute() or resolved != path or path == Path(path.anchor) or (board_id is not None and board_id not in path.parts) or (parent is not None and (not resolved.is_relative_to(parent.resolve()) or resolved == parent.resolve())):
        raise StorageConfigurationError('Board cleanup path escaped or redirected its captured directory')
    if path.exists():
        if not path.is_dir():
            raise StorageConfigurationError('Board cleanup expected a directory; preserve the unexpected file')
        shutil.rmtree(path)

def delete_files(store, row):
    if row['state'] == 'done':
        return {'new_path': '', 'files_pending': False}
    if row['state'] == 'pending':
        home = Path(row['owner_home'])
        _remove_directory(home / 'kanban' / 'boards' / row['slug'], parent=home / 'kanban' / 'boards')
        _remove_directory(home / 'kanban' / 'boards' / '_archived' / f"{row['slug']}-{row['board_id']}", parent=home / 'kanban' / 'boards' / '_archived')
        set_job_state(store, row['board_id'], 'content_pending')
    roots = sorted({row[name] for name in ROOT_FIELDS}, key=lambda value: len(Path(value).parts))
    with store.write() as conn:
        lock_files(conn, store)
        reason = _references(conn, store, roots)
    if reason is not None:
        return {'new_path': '', 'files_pending': True, 'files_pending_reason': reason}
    selected = []
    for root in roots:
        if not any(Path(root).is_relative_to(Path(previous)) for previous in selected):
            selected.append(root)
    for root in selected:
        _remove_directory(root, board_id=row['board_id'])
    set_job_state(store, row['board_id'], 'done')
    return {'new_path': '', 'files_pending': False}
ROOT_FIELDS = ('data_root', 'attachments_root', 'workspaces_root', 'logs_root')

@contextmanager
def local_files_lock(home):
    from pm.filesystem import lock_path, unlock_fd
    descriptor = lock_path(Path(home) / 'kanban' / '.board-files.lock', timeout=10, create_dir=True)
    if descriptor is None:
        raise StorageBusyError('Local Board files are being changed; retry after the operation completes')
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)

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

def prepare(store, row):
    frame = BoardFiles(store.scope.profile_home, row['board_id'], row['slug'])
    data = content_root(frame)
    if data.resolve() != frame.home.resolve() / 'kanban' / 'data' / frame.board_id:
        raise StorageConfigurationError('Board data generation is redirected; preserve it for manual reconciliation')
    fields = dict(owner_home=str(frame.home), data_root=str(data.resolve()))
    for name, env_var, leaf in (('attachments_root', 'HERMES_KANBAN_ATTACHMENTS_ROOT', 'attachments'), ('workspaces_root', 'HERMES_KANBAN_WORKSPACES_ROOT', 'workspaces'), ('logs_root', None, 'logs')):
        root = _path(frame, env_var, leaf)
        override = os.environ.get(env_var, '').strip() if env_var else ''
        expected = Path(override).expanduser().resolve() / frame.board_id if override else frame.home.resolve() / 'kanban' / 'data' / frame.board_id / leaf
        if root.resolve() != expected:
            raise StorageConfigurationError('Board content root contains a redirected generation path; preserve it for manual reconciliation')
        fields[name] = str(expected)
    return fields

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

def _archive_files(row):
    from utils import atomic_json_write
    from hermes_cli.kanban_db_boards import _read_metadata_file
    home = Path(row['owner_home'])
    boards_root = home / 'kanban' / 'boards'
    source = boards_root / row['slug']
    target = boards_root / '_archived' / f"{row['slug']}-{row['board_id']}"
    resolved_root = boards_root.resolve()
    if any(not path.resolve().is_relative_to(resolved_root) or path.resolve() == resolved_root for path in (source, target)):
        raise StorageConfigurationError('Board archive paths escape the owning boards directory')
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            source.rename(target)
        else:
            target.mkdir()
    metadata_path = target / 'board.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.exists() else _read_metadata_file(row['slug'])
    metadata.pop('db_path', None)
    metadata.update(slug=row['slug'], archived=True)
    source.mkdir(parents=True, exist_ok=True)
    atomic_json_write(metadata_path, metadata, indent=2)
    atomic_json_write(target / 'contents.json', {'backend': 'postgresql', 'board_id': row['board_id'], 'roots': {name: row[name] for name in ROOT_FIELDS}}, indent=2)
    atomic_json_write(source / 'board.json', metadata, indent=2)
    return str(target)

def _read_job(store, board_id):
    from hermes_db.domains.kanban.postgres.repository import decode_record
    with store.read() as conn:
        raw = conn.execute(select(jobs).where(job_key(store, board_id))).mappings().one()
        row = decode_record(raw)
    if Path(row['owner_home']).resolve() != store.scope.profile_home:
        raise StorageConfigurationError('Board file operation belongs to another local Profile home')
    return row

def set_job_state(store, board_id, state):
    with store.write() as conn:
        lock_files(conn, store)
        conn.execute(update(jobs).where(job_key(store, board_id)).values(state=state))

def pending_delete(store, slug):
    with store.read() as conn:
        return conn.scalar(select(jobs.c.board_id).where(jobs.c.store_id == store.scope.require_store_id(), jobs.c.slug == slug, jobs.c.action == 'delete', jobs.c.state != 'done', jobs.c.owner_home == encode_text(str(store.scope.profile_home))))

def settle_import_stage(store, board_id):
    with store.read() as conn:
        row = conn.execute(select(jobs.c.action, jobs.c.state, jobs.c.stage_root).where(job_key(store, board_id))).first()
    if row is not None and row.action == 'import' and (row.state == 'done') and (row.stage_root is not None):
        run_job(store, board_id)

def run_job(store, board_id):
    with local_files_lock(store.scope.profile_home):
        row = _read_job(store, board_id)
        if row['action'] == 'import':
            from hermes_db.domains.kanban.postgres.transfer import finish_import
            return finish_import(store, row)
        if row['action'] == 'delete':
            from hermes_db.domains.kanban.postgres.files import delete_files
            return delete_files(store, row)
        target = str(Path(row['owner_home']) / 'kanban' / 'boards' / '_archived' / f"{row['slug']}-{board_id}")
        if row['state'] != 'done':
            target = _archive_files(row)
            set_job_state(store, board_id, 'done')
        return {'new_path': target, 'files_pending': False}
