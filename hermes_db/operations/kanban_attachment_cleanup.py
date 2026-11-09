"""Retired attachment paths remain fenced until unlink succeeds, including after restart."""

from pathlib import Path
import json
import re
from uuid import uuid4
from sqlalchemy import select, update

from hermes_db.core.resource import DomainResource
from hermes_db.errors import StorageConfigurationError, StorageBusyError
from hermes_db.operations.kanban_file_jobs import local_files_lock, lock_files
from hermes_db.tables.kanban_artifacts import attachments, blobs
from hermes_db.core.values import decode_text, encode_text


def _owner(resource):
    from hermes_db.integration.transfer.move_values import resource_key
    return dict(home=str(resource.scope.profile_home), store_id=resource.scope.require_store_id(), target=resource_key(resource._transactions))


def prepare_directory(resource, parent):
    from utils import atomic_json_write
    directory = Path(parent) / uuid4().hex
    if directory.resolve() != directory:
        raise StorageConfigurationError("Attachment preparation directory is redirected")
    directory.mkdir(parents=True)
    atomic_json_write(directory / ".owner.json", _owner(resource), mode=0o600)
    return directory


def discard_empty_generation(resource, directory):
    marker = directory / ".owner.json"
    if (directory.resolve() == directory and marker.is_file() and not marker.is_symlink()
            and json.loads(marker.read_text(encoding="utf-8-sig")) == _owner(resource)
            and set(directory.iterdir()) == {marker}):
        marker.unlink()
        directory.rmdir()


def discard_copies(resource, staged):
    from hermes_cli import kanban_db as kb
    kb._discard_staged_copies(staged, staged[0].parent)
    discard_empty_generation(resource, staged[0].parent)


def finish(resource, path, token, *, blob_path=None):
    from hermes_db.repositories.kanban_workspaces import canonical_path
    original = str(path) if blob_path is None else blob_path
    path = Path(path)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise StorageConfigurationError("Attachment cleanup path is relative or redirected; preserve its file")
    path = path.resolve()
    key = canonical_path(path)
    with DomainResource.write(resource) as conn:
        lock_files(conn, resource)
        held = conn.scalar(select(blobs.c.cleanup_token).where(blobs.c.store_id == resource.scope.require_store_id(),
            blobs.c.path == encode_text(original)))
        live = conn.scalar(select(attachments.c.id).where(attachments.c.store_id == resource.scope.require_store_id(),
            (attachments.c.path_key == encode_text(key)) | attachments.c.path_key.is_(None)).limit(1))
        if held != token:
            raise StorageBusyError("Attachment cleanup token changed; preserve its file")
        if live is not None:
            raise StorageBusyError("Retired attachment path still has a live or unresolved reference; preserve its file")
    if path.is_dir():
        raise StorageConfigurationError("Attachment cleanup expected a file")
    path.unlink(missing_ok=True)
    with DomainResource.write(resource) as conn:
        conn.execute(update(blobs).where(blobs.c.store_id == resource.scope.require_store_id(),
            blobs.c.path == encode_text(original), blobs.c.cleanup_token == token).values(cleanup_token=None))


def reconcile(resource):
    with local_files_lock(resource.scope.profile_home):
        with DomainResource.write(resource) as conn:
            lock_files(conn, resource)
        with resource.read() as conn:
            pending = list(conn.execute(select(blobs.c.path, blobs.c.cleanup_token).where(
                blobs.c.store_id == resource.scope.require_store_id(), blobs.c.cleanup_token.is_not(None))))
            live = set(conn.scalars(select(attachments.c.path_key).where(attachments.c.store_id == resource.scope.require_store_id())))
        if None in live:
            raise StorageBusyError("Unresolved attachment paths require reconciliation before file cleanup")
        for raw, token in pending:
            finish(resource, decode_text(raw), token)
        _orphans(resource, live)


def _orphans(resource, live):
    from hermes_db.domains.kanban_files import BoardFiles, _path
    from hermes_db.tables.kanban import kanban_boards
    with resource.read() as conn:
        boards = list(conn.execute(select(kanban_boards.c.board_id, kanban_boards.c.slug).where(
            kanban_boards.c.store_id == resource.scope.require_store_id())))
    owner = _owner(resource)
    for board_id, slug in boards:
        root = _path(BoardFiles(resource.scope.profile_home, board_id, slug), "HERMES_KANBAN_ATTACHMENTS_ROOT", "attachments")
        for marker in root.glob("*/*/.owner.json"):
            _sweep_generation(marker, root, owner, live)


def _sweep_generation(marker, root, owner, live):
    from hermes_db.repositories.kanban_workspaces import canonical_path
    directory = marker.parent
    if not re.fullmatch("[0-9a-f]{32}", directory.name):
        return
    if directory.resolve() != directory or marker.is_symlink() or not directory.is_relative_to(root):
        raise StorageConfigurationError("Attachment preparation generation is redirected")
    if json.loads(marker.read_text(encoding="utf-8-sig")) != owner:
        return
    retained = False
    for path in directory.iterdir():
        if path == marker:
            continue
        if encode_text(canonical_path(path)) in live:
            retained = True
        elif path.is_file() and not path.is_symlink():
            path.unlink()
        else:
            raise StorageConfigurationError("Unexpected content in private attachment generation")
    if not retained:
        marker.unlink()
        directory.rmdir()
