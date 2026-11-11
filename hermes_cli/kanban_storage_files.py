"""Application attachment/file authorization and retirement; short SQL fences stay business-owned."""
import contextlib
import json
import os
import re
import shutil
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.domains.kanban.postgres import files as db, repository as repo
from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageBusyError, UnknownCommitError, StorageConfigurationError
from hermes_db.core.values import encode_text, decode_text as _decode_text



def add_attachment(store, task_id, *, filename, stored_path, content_type=None, size=0, uploaded_by=None):
    _preflight_reference(store, stored_path)
    with local_files_lock(store.scope.profile_home):
        _preflight_reference(store, stored_path)
        return _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by)


def _preflight_reference(store, path):
    from hermes_db.domains.kanban.postgres.files import guard_reference
    from hermes_cli.kanban_storage_owner import canonical_path
    key = canonical_path(path)
    pending = db.pending_blob_paths(store, key)
    from hermes_db.core.values import decode_text
    if any(canonical_path(decode_text(raw)) == key for raw in pending):
        raise StorageBusyError('Attachment file cleanup is pending; retain the file and retry after reconciliation')


def _add_attachment(store, task_id, filename, stored_path, content_type, size, uploaded_by):
    if not filename or not filename.strip():
        raise ValueError('attachment filename is required')
    if not stored_path or not stored_path.strip():
        raise ValueError('attachment stored_path is required')
    from hermes_cli.kanban_storage_owner import canonical_path
    stored_path = str(Path(stored_path).expanduser().resolve())
    file_key = canonical_path(stored_path)
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        attachment_id = db.insert_attachment(conn, store, task_id, filename=filename.strip(), stored_path=stored_path, file_key=file_key, content_type=content_type, size=size, uploaded_by=uploaded_by)
        return store.command_result(conn, attachment_id)


def store_attachment_bytes(store, task_id, filename, data, *, content_type=None, uploaded_by=None, board=None, max_bytes=None):
    with local_files_lock(store.scope.profile_home):
        return _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes)


def _store_attachment_bytes(store, task_id, filename, data, content_type, uploaded_by, board, max_bytes):

    if board is not None and _storage_shared_1._require_slug(board) != store.slug:
        raise ValueError('attachment Board must match its acquired Board resource')
    max_bytes = _storage_shared_1.KANBAN_ATTACHMENT_MAX_BYTES if max_bytes is None else max_bytes
    if len(data) > max_bytes:
        raise store.result_values.attachment_too_large(f'attachment exceeds {max_bytes // (1024 * 1024)} MB limit')
    safe_name = _storage_shared_1._safe_attachment_name(filename)
    directory = prepare_directory(store, store.files.task_attachments_dir(task_id, board=store.slug))
    path = directory / safe_name
    try:
        path.write_bytes(data)
        return _add_attachment(store, task_id, safe_name, str(path.resolve()), content_type, len(data), uploaded_by)
    except UnknownCommitError:
        raise
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
            discard_empty_generation(store, directory)
        raise


def _retire_attachment(store, attachment_id):

    from hermes_cli.kanban_storage_owner import canonical_path
    captured = db.get_attachment(store, attachment_id)
    file_key = canonical_path(captured.stored_path) if captured is not None else None
    return db.retire_attachment(store, attachment_id, captured, file_key)


def delete_attachment(store, attachment_id):
    with local_files_lock(store.scope.profile_home):
        attachment, token = _retire_attachment(store, attachment_id)
        if token is not None:
            from hermes_cli.kanban_storage_owner import canonical_path
            finish(store, attachment.stored_path, token, blob_path=canonical_path(attachment.stored_path))
    return attachment


def _owner(resource):
    from hermes_db.core.values import resource_key
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

    resource.files.discard_staged_copies(staged, staged[0].parent)
    discard_empty_generation(resource, staged[0].parent)


def finish(resource, path, token, *, blob_path=None):
    from hermes_cli.kanban_storage_owner import canonical_path
    original = str(path) if blob_path is None else blob_path
    path = Path(path)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise StorageConfigurationError('Attachment cleanup path is relative or redirected; preserve its file')
    path = path.resolve()
    key = canonical_path(path)
    db.verify_retired_blob(resource, original, key, token)
    if path.is_dir():
        raise StorageConfigurationError('Attachment cleanup expected a file')
    path.unlink(missing_ok=True)
    db.clear_retired_blob(resource, original, token)


def reconcile(resource):
    with local_files_lock(resource.scope.profile_home):
        pending, live = db.attachment_cleanup_snapshot(resource)
        if None in live:
            raise StorageBusyError('Unresolved attachment paths require reconciliation before file cleanup')
        for raw, token in pending:
            finish(resource, _decode_text(raw), token)
        _orphans(resource, live)


def _orphans(resource, live):
    boards = db.attachment_boards(resource)
    owner = _owner(resource)
    for board_id, slug in boards:
        root = resource.files.board_path(board_id, slug, 'HERMES_KANBAN_ATTACHMENTS_ROOT', 'attachments')
        for marker in root.glob('*/*/.owner.json'):
            _sweep_generation(marker, root, owner, live)


def _sweep_generation(marker, root, owner, live):
    from hermes_cli.kanban_storage_owner import canonical_path
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
    from hermes_db.core.values import resource_key
    marker = root / 'command.json'
    owner = manifest['owner']
    if owner['store_id'] != resource.scope.require_store_id() or manifest.get('board_target') != resource_key(resource._transactions) or Path(owner['profile_home']).resolve() != resource.scope.profile_home:
        return False
    if marker.is_file() and (not marker.is_symlink()):
        command = json.loads(marker.read_text(encoding='utf-8'))  # windows-footgun: ok -- Private command.json is written by atomic_json_write; retain the original strict marker protocol.
        found = db.completed_upload_command(resource, owner, command)
        if found is not None:
            return True
    return resource.files.terminal_execution(manifest['session_store'], manifest['execution_id'], manifest['generation'])


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
        db.set_job_state(store, row['board_id'], 'content_pending')
    roots = sorted({row[name] for name in db.ROOT_FIELDS}, key=lambda value: len(Path(value).parts))
    reason = db.retired_root_references(store, roots)
    if reason is not None:
        return {'new_path': '', 'files_pending': True, 'files_pending_reason': reason}
    selected = []
    for root in roots:
        if not any(Path(root).is_relative_to(Path(previous)) for previous in selected):
            selected.append(root)
    for root in selected:
        _remove_directory(root, board_id=row['board_id'])
    db.set_job_state(store, row['board_id'], 'done')
    return {'new_path': '', 'files_pending': False}


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


def prepare(store, row):
    home, board_id = store.scope.profile_home, row['board_id']
    data = store.files.content_root(row['board_id'], row['slug'])
    if data.resolve() != home.resolve() / 'kanban' / 'data' / board_id:
        raise StorageConfigurationError('Board data generation is redirected; preserve it for manual reconciliation')
    fields = dict(owner_home=str(home), data_root=str(data.resolve()))
    for name, env_var, leaf in (('attachments_root', 'HERMES_KANBAN_ATTACHMENTS_ROOT', 'attachments'), ('workspaces_root', 'HERMES_KANBAN_WORKSPACES_ROOT', 'workspaces'), ('logs_root', None, 'logs')):
        root = store.files.board_path(row['board_id'], row['slug'], env_var, leaf)
        override = os.environ.get(env_var, '').strip() if env_var else ''
        expected = Path(override).expanduser().resolve() / board_id if override else home.resolve() / 'kanban' / 'data' / board_id / leaf
        if root.resolve() != expected:
            raise StorageConfigurationError('Board content root contains a redirected generation path; preserve it for manual reconciliation')
        fields[name] = str(expected)
    return fields


def _archive_files(store, row):
    from utils import atomic_json_write

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
    metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.exists() else store.files.read_metadata_file(row['slug'])
    metadata.pop('db_path', None)
    metadata.update(slug=row['slug'], archived=True)
    source.mkdir(parents=True, exist_ok=True)
    atomic_json_write(metadata_path, metadata, indent=2)
    atomic_json_write(target / 'contents.json', {'backend': 'postgresql', 'board_id': row['board_id'], 'roots': {name: row[name] for name in db.ROOT_FIELDS}}, indent=2)
    atomic_json_write(source / 'board.json', metadata, indent=2)
    return str(target)


def _read_job(store, board_id):
    from hermes_db.domains.kanban.postgres.repository import decode_record
    row = db.read_job(store, board_id)
    if Path(row['owner_home']).resolve() != store.scope.profile_home:
        raise StorageConfigurationError('Board file operation belongs to another local Profile home')
    return row


def settle_import_stage(store, board_id):
    row = db.import_stage_status(store, board_id)
    if row is not None and row.action == 'import' and (row.state == 'done') and (row.stage_root is not None):
        run_job(store, board_id)


def run_job(store, board_id):
    with local_files_lock(store.scope.profile_home):
        row = _read_job(store, board_id)
        if row['action'] == 'import':
            return store.files.finish_import(store, row)
        if row['action'] == 'delete':
            return delete_files(store, row)
        target = str(Path(row['owner_home']) / 'kanban' / 'boards' / '_archived' / f"{row['slug']}-{board_id}")
        if row['state'] != 'done':
            target = _archive_files(store, row)
            db.set_job_state(store, board_id, 'done')
        return {'new_path': target, 'files_pending': False}
