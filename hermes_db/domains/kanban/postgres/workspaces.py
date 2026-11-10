"""Kanban workspaces workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
import logging
_kanban_logger = logging.getLogger("hermes_cli.kanban_db")
from pathlib import Path
from sqlalchemy import and_, or_, select, update, delete
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban import tasks, links
from hermes_db.core.values import decode_text, encode_text
import json
from uuid import uuid4
from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageError, StorageBusyError
from hermes_db.tables.kanban_workspaces import paths, references
import os
from sqlalchemy.dialects.postgresql import insert
TERMINAL = (b'done', b'archived', b'failed', b'cancelled')

def _cleanup_workspace(store, task_id):
    from hermes_db.domains.kanban.postgres.workspaces import cleanup_workspace
    cleanup_workspace(store, task_id)

def gc_archived_workspaces(store):

    from hermes_db.domains.kanban.postgres.workspaces import cleanup_workspace
    removed = 0
    for task in store.list_tasks(status='archived', include_archived=True):
        if task.workspace_kind not in {'scratch', 'worktree'}:
            continue
        path = Path(task.workspace_path or store.files.workspaces_root(board=store.slug) / task.id)
        if not path.is_dir() or path.is_symlink():
            continue
        if task.workspace_path is None:
            set_workspace_path(store, task.id, str(path))
        cleanup_workspace(store, task.id)
        removed += not path.exists()
    return removed

def _has_active_children(store, task_id):
    query = select(tasks.c.id).join(links, and_(tasks.c.store_id == links.c.store_id, tasks.c.board_id == links.c.board_id, tasks.c.id == links.c.child_id))
    with store.read() as conn:
        return conn.scalar(query.where(repo.scope(tasks, store), links.c.parent_id == encode_text(task_id), tasks.c.status.not_in(TERMINAL)).limit(1)) is not None

def _is_terminal_task(store, task_id):
    with store.read() as conn:
        return conn.scalar(select(tasks.c.id).where(repo.key(store, task_id), tasks.c.status.in_(TERMINAL))) is not None

def _workspace_in_use_by_other(store, task_id, path):

    from hermes_db.domains.kanban.rules import _path_key
    try:
        key = _path_key(Path(path).expanduser().resolve(strict=False))
    except OSError as error:
        _kanban_logger.warning('Cannot resolve workspace for task %s: %s', task_id, error)
        return 'unknown'
    with store.read() as conn:
        paths = list(conn.scalars(select(tasks.c.workspace_path).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL), tasks.c.workspace_path.is_not(None), or_(tasks.c.board_id != store.board_id, tasks.c.id != encode_text(task_id)))))
    for value in paths:
        other = decode_text(value)
        if not other:
            continue
        try:
            if _path_key(Path(other).expanduser().resolve(strict=False)) == key:
                return 'shared'
        except OSError:
            return 'unknown'
    return None

def set_workspace_path(store, task_id, path):
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path, register
    key = canonical_path(path)
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        register(conn, store, task_id, key)
        repo.task_update(conn, store, task_id, workspace_path=str(path))

def set_branch_name(store, task_id, branch_name):
    with store.write() as conn:
        repo.task_update(conn, store, task_id, branch_name=str(branch_name))

def _active_children(conn, store, task_id):
    return conn.scalar(select(tasks.c.id).join(links, (tasks.c.store_id == links.c.store_id) & (tasks.c.board_id == links.c.board_id) & (tasks.c.id == links.c.child_id)).where(repo.scope(tasks, store), links.c.parent_id == task_id.encode(), tasks.c.status.not_in(TERMINAL)).limit(1)) is not None

def _reserve(store, task, path_key):
    from hermes_db.domains.kanban.postgres.files import lock_files
    with DomainResource.write(store) as conn:
        lock_files(conn, store)
        current = repo.get(conn, store, task['id'])
        if current is None or any(current[name] != task[name] for name in ('status', 'workspace_kind', 'workspace_path', 'branch_name')):
            return None
        if current['status'].encode() not in TERMINAL or _active_children(conn, store, task['id']):
            return None
        if key_for_task(conn, store, task['id']) != path_key:
            return None
        existing = conn.scalar(select(paths.c.cleanup_token).where(path_scope(store, path_key)).with_for_update())
        if existing is None:
            lock_path(conn, store, path_key)
        reason = live_references(conn, store, path_key)
        if reason is not None:
            repo.event(conn, store, task['id'], 'workspace_cleanup_deferred_shared', {'path': task['workspace_path'], 'reason': reason})
            return None
        token = existing or uuid4().hex
        payload = json.dumps(dict(task=task, board_id=store.board_id, slug=store.slug), ensure_ascii=True).encode()
        conn.execute(update(paths).where(path_scope(store, path_key)).values(cleanup_token=token, cleanup_payload=payload))
        return token

def _clean_one(store, task_id):

    with store.read() as conn:
        task = repo.get(conn, store, task_id)
    if task is None or not task['workspace_path'] or task['workspace_kind'] not in _storage_shared_1._REMOVABLE_KINDS:
        return
    path = Path(task['workspace_path']).expanduser()
    scratch = task['workspace_kind'] == 'scratch'
    if scratch and (not store.files.is_managed_scratch_path(path)):
        return
    if path.exists() and (not scratch) and (not store.files.is_linked_worktree_checkout(path)):
        return
    path_key = canonical_path(path)
    token = _reserve(store, task, path_key)
    if token is None:
        return
    _remove(store, task, path)
    _finish(store, path_key, token)

def _remove(store, task, path):

    task_id = task['id']
    scratch = task['workspace_kind'] == 'scratch'
    if path.exists():
        store.files.cleanup_worker_tmux(store, task_id)
        if scratch:
            store.files.release_lsp_clients(str(path))
            store.files.remove_tree(path)
        else:
            store.files.cleanup_worktree_workspace(task_id, str(path), task['branch_name'])

def _finish(store, path_key, token):
    with DomainResource.write(store) as conn:
        conn.execute(update(paths).where(path_scope(store, path_key), paths.c.cleanup_token == token).values(cleanup_token=None, cleanup_payload=None))

def resume_pending(store, task, path_key, token):

    from hermes_db.domains.kanban.postgres.files import lock_files
    from hermes_db.errors import StorageConfigurationError, StorageBusyError
    path = Path(task['workspace_path']).expanduser()
    if canonical_path(path) != path_key or path.resolve() != path:
        raise StorageConfigurationError('Captured workspace cleanup path changed')
    if task['workspace_kind'] == 'scratch':
        if not store.files.is_managed_scratch_path(path):
            raise StorageConfigurationError('Captured scratch cleanup is outside managed storage')
    elif task['workspace_kind'] != 'worktree' or (path.exists() and (not store.files.is_linked_worktree_checkout(path))):
        raise StorageConfigurationError('Captured worktree cleanup no longer identifies a linked worktree')
    with DomainResource.write(store) as conn:
        lock_files(conn, store)
        current = conn.scalar(select(paths.c.cleanup_token).where(path_scope(store, path_key)).with_for_update())
        if current != token:
            return
        if live_references(conn, store, path_key) is not None or _active_children(conn, store, task['id']):
            raise StorageBusyError('Captured cleanup still has live workspace users')
    _remove(store, task, path)
    _finish(store, path_key, token)

def cleanup_workspace(store, task_id):

    try:
        with store.read() as conn:
            parents = repo.linked_ids(conn, store, task_id, parents=True)
        from hermes_db.domains.kanban.postgres.files import local_files_lock
        with local_files_lock(store.scope.profile_home):
            for candidate in [task_id, *parents]:
                _clean_one(store, candidate)
    except (StorageError, OSError) as error:
        _kanban_logger.warning('Workspace cleanup deferred for task %s: %s', task_id, error)
TERMINAL = (b'done', b'archived', b'failed', b'cancelled')

def canonical_path(path):
    from hermes_db.domains.kanban.rules import _path_key
    return os.path.normcase(_path_key(Path(path).expanduser().resolve(strict=False))) if path else None

def path_scope(store, key):
    return and_(paths.c.store_id == store.scope.require_store_id(), paths.c.path_key == encode_text(key))

def reference_scope(store, task_id):
    return and_(references.c.store_id == store.scope.require_store_id(), references.c.board_id == store.board_id, references.c.task_id == encode_text(task_id))

def lock_path(conn, store, key):
    from hermes_db.domains.kanban.postgres.files import guard_reference
    guard_reference(conn, store, key)
    conn.execute(insert(paths).values(store_id=store.scope.require_store_id(), path_key=encode_text(key)).on_conflict_do_nothing())
    token = conn.scalar(select(paths.c.cleanup_token).where(path_scope(store, key)).with_for_update())
    if token is not None:
        raise StorageBusyError('Workspace cleanup is pending; retain the workspace and retry after reconciliation')

def register(conn, store, task_id, key):
    if key is None:
        conn.execute(delete(references).where(reference_scope(store, task_id)))
        return
    lock_path(conn, store, key)
    conn.execute(insert(references).values(store_id=store.scope.require_store_id(), board_id=store.board_id, task_id=encode_text(task_id), path_key=encode_text(key)).on_conflict_do_update(index_elements=[references.c.store_id, references.c.board_id, references.c.task_id], set_={'path_key': encode_text(key)}))

def key_for_task(conn, store, task_id):
    from hermes_db.core.values import decode_text
    return decode_text(conn.scalar(select(references.c.path_key).where(reference_scope(store, task_id))))

def guard_live_task(conn, store, task_id):
    from hermes_db.core.values import decode_text
    parent_ids = select(links.c.parent_id).where(links.c.store_id == store.scope.require_store_id(), links.c.board_id == store.board_id, links.c.child_id == encode_text(task_id))
    keys = conn.scalars(select(references.c.path_key).where(references.c.store_id == store.scope.require_store_id(), references.c.board_id == store.board_id, or_(references.c.task_id == encode_text(task_id), references.c.task_id.in_(parent_ids))).distinct().order_by(references.c.path_key))
    for key in list(keys):
        lock_path(conn, store, decode_text(key))

def guard_parent_link(conn, store, parent_id, child_id):
    from hermes_db.domains.kanban.postgres.repository import key
    status = conn.scalar(select(tasks.c.status).where(key(store, child_id)))
    path = key_for_task(conn, store, parent_id)
    if path is not None and status not in TERMINAL:
        lock_path(conn, store, path)

def live_references(conn, store, path_key):
    own = and_(tasks.c.store_id == references.c.store_id, tasks.c.board_id == references.c.board_id, tasks.c.id == references.c.task_id)
    live = conn.scalar(select(tasks.c.id).join(references, own).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL), references.c.path_key == encode_text(path_key)).limit(1))
    if live is not None:
        return 'shared'
    missing = conn.scalar(select(tasks.c.id).outerjoin(references, own).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL), tasks.c.workspace_path.is_not(None), references.c.task_id.is_(None)).limit(1))
    return 'unknown' if missing is not None else None
