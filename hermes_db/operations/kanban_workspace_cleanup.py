"""Commit deletion intent before touching files; new references see a durable fence."""

from pathlib import Path
from uuid import uuid4
from sqlalchemy import select, update

from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageError
from hermes_db.repositories import kanban as repo, kanban_workspaces as workspaces
from hermes_db.tables.kanban import tasks, links
from hermes_db.tables.kanban_workspaces import paths


def _active_children(conn, store, task_id):
    return conn.scalar(select(tasks.c.id).join(links, (tasks.c.store_id == links.c.store_id)
        & (tasks.c.board_id == links.c.board_id) & (tasks.c.id == links.c.child_id))
        .where(repo.scope(tasks, store), links.c.parent_id == task_id.encode(),
               tasks.c.status.not_in(workspaces.TERMINAL)).limit(1)) is not None


def _reserve(store, task, path_key):
    with store.write() as conn:
        current = repo.get(conn, store, task["id"])
        if current is None or any(current[name] != task[name] for name in ("status", "workspace_kind", "workspace_path", "branch_name")):
            return None
        if current["status"].encode() not in workspaces.TERMINAL or _active_children(conn, store, task["id"]):
            return None
        if workspaces.key_for_task(conn, store, task["id"]) != path_key:
            return None
        workspaces.lock_path(conn, store, path_key)
        reason = workspaces.live_references(conn, store, path_key)
        if reason is not None:
            repo.event(conn, store, task["id"], "workspace_cleanup_deferred_shared",
                       {"path": task["workspace_path"], "reason": reason})
            return None
        token = uuid4().hex
        conn.execute(update(paths).where(workspaces.path_scope(store, path_key)).values(cleanup_token=token))
        return token


def _clean_one(store, task_id):
    from hermes_cli import kanban_db_workspace as native
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
    if task is None or not task["workspace_path"] or task["workspace_kind"] not in native._REMOVABLE_KINDS:
        return
    path = Path(task["workspace_path"]).expanduser()
    if not path.is_dir():
        return
    scratch = task["workspace_kind"] == "scratch"
    if scratch and not native._is_managed_scratch_path(path):
        return
    if not scratch and not native._is_linked_worktree_checkout(path):
        return
    path_key = workspaces.canonical_path(path)
    token = _reserve(store, task, path_key)
    if token is None:
        return
    # Any interruption retains the token for explicit maintenance reconciliation.
    native._cleanup_worker_tmux(store, task_id)
    if scratch:
        native.release_lsp_clients(str(path))
        native.shutil.rmtree(path)
    else:
        native._cleanup_worktree_workspace(task_id, str(path), task["branch_name"])
    with DomainResource.write(store) as conn:
        conn.execute(update(paths).where(workspaces.path_scope(store, path_key), paths.c.cleanup_token == token)
                     .values(cleanup_token=None))


def cleanup_workspace(store, task_id):
    from hermes_cli import kanban_db as kb
    try:
        with store.read() as conn:
            parents = repo.linked_ids(conn, store, task_id, parents=True)
        for candidate in [task_id, *parents]:
            _clean_one(store, candidate)
    except (StorageError, OSError) as error:
        kb._log.warning("Workspace cleanup deferred for task %s: %s", task_id, error)
