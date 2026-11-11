"""Captured workspace path policy and original fenced cleanup orchestration."""
import logging
from pathlib import Path
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageError
from hermes_db.core.values import decode_text
from hermes_cli.kanban_storage_owner import canonical_path
_kanban_logger = logging.getLogger("hermes_cli.kanban_db")

def _cleanup_workspace(store, task_id):
    cleanup_workspace(store, task_id)

def gc_archived_workspaces(store):

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

def _workspace_in_use_by_other(store, task_id, path):
    from hermes_db.domains.kanban.postgres import workspaces as db

    from hermes_db.domains.kanban.rules import _path_key
    try:
        key = _path_key(Path(path).expanduser().resolve(strict=False))
    except OSError as error:
        _kanban_logger.warning('Cannot resolve workspace for task %s: %s', task_id, error)
        return 'unknown'
    paths = db.other_workspace_paths(store, task_id)
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
    from hermes_db.domains.kanban.postgres import workspaces as db
    key = canonical_path(path)
    with store.write() as conn:
        db.set_workspace_reference(conn, store, task_id, path, key)

def _clean_one(store, task_id):
    from hermes_db.domains.kanban.postgres import workspaces as db

    task = db.cleanup_candidate(store, task_id)
    if task is None or not task['workspace_path'] or task['workspace_kind'] not in _storage_shared_1._REMOVABLE_KINDS:
        return
    path = Path(task['workspace_path']).expanduser()
    scratch = task['workspace_kind'] == 'scratch'
    if scratch and (not store.files.is_managed_scratch_path(path)):
        return
    if path.exists() and (not scratch) and (not store.files.is_linked_worktree_checkout(path)):
        return
    path_key = canonical_path(path)
    token = db._reserve(store, task, path_key)
    if token is None:
        return
    _remove(store, task, path)
    db._finish(store, path_key, token)

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

def resume_pending(store, task, path_key, token):
    from hermes_db.domains.kanban.postgres import workspaces as db

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
        if not db.require_cleanup_reservation(conn, store, task, path_key, token):
            return
    _remove(store, task, path)
    db._finish(store, path_key, token)

def cleanup_workspace(store, task_id):
    from hermes_db.domains.kanban.postgres import repository as repo

    try:
        with store.read() as conn:
            parents = repo.linked_ids(conn, store, task_id, parents=True)
        from hermes_cli.kanban_storage_files import local_files_lock
        with local_files_lock(store.scope.profile_home):
            for candidate in [task_id, *parents]:
                _clean_one(store, candidate)
    except (StorageError, OSError) as error:
        _kanban_logger.warning('Workspace cleanup deferred for task %s: %s', task_id, error)
