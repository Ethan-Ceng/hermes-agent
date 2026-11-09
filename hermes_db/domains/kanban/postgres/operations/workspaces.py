"""Detached workspace fields and cross-Board live-reference queries."""

from pathlib import Path
from sqlalchemy import and_, or_, select

from hermes_db.domains.kanban.postgres.queries import kanban as repo
from hermes_db.tables.kanban import tasks, links
from hermes_db.core.values import decode_text, encode_text

TERMINAL = (b"done", b"archived", b"failed", b"cancelled")


def _cleanup_workspace(store, task_id):
    from hermes_db.domains.kanban.postgres.operations.workspace_cleanup import cleanup_workspace
    cleanup_workspace(store, task_id)


def gc_archived_workspaces(store):
    from hermes_cli import kanban_db as kb
    from hermes_db.domains.kanban.postgres.operations.workspace_cleanup import cleanup_workspace
    removed = 0
    for task in kb.list_tasks(store, status="archived", include_archived=True):
        if task.workspace_kind not in {"scratch", "worktree"}:
            continue
        path = Path(task.workspace_path or (kb.workspaces_root(board=store.slug) / task.id))
        if not path.is_dir() or path.is_symlink():
            continue
        if task.workspace_path is None:
            set_workspace_path(store, task.id, str(path))
        cleanup_workspace(store, task.id)
        removed += not path.exists()
    return removed


def _has_active_children(store, task_id):
    query = select(tasks.c.id).join(links, and_(tasks.c.store_id == links.c.store_id,
        tasks.c.board_id == links.c.board_id, tasks.c.id == links.c.child_id))
    with store.read() as conn:
        return conn.scalar(query.where(repo.scope(tasks, store), links.c.parent_id == encode_text(task_id),
            tasks.c.status.not_in(TERMINAL)).limit(1)) is not None


def _is_terminal_task(store, task_id):
    with store.read() as conn:
        return conn.scalar(select(tasks.c.id).where(repo.key(store, task_id), tasks.c.status.in_(TERMINAL))) is not None


def _workspace_in_use_by_other(store, task_id, path):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_workspace import _path_key
    try:
        key = _path_key(Path(path).expanduser().resolve(strict=False))
    except OSError as error:
        kb._log.warning("Cannot resolve workspace for task %s: %s", task_id, error)
        return "unknown"
    with store.read() as conn:
        paths = list(conn.scalars(select(tasks.c.workspace_path).where(
            tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL),
            tasks.c.workspace_path.is_not(None), or_(tasks.c.board_id != store.board_id, tasks.c.id != encode_text(task_id)))))
    # Symlink and filesystem lookups must not retain a connection.
    for value in paths:
        other = decode_text(value)
        if not other:
            continue
        try:
            if _path_key(Path(other).expanduser().resolve(strict=False)) == key:
                return "shared"
        except OSError:
            return "unknown"
    return None


def set_workspace_path(store, task_id, path):
    from hermes_db.domains.kanban.postgres.queries.workspaces import canonical_path, register
    key = canonical_path(path)
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        register(conn, store, task_id, key)
        repo.task_update(conn, store, task_id, workspace_path=str(path))


def set_branch_name(store, task_id, branch_name):
    with store.write() as conn:
        repo.task_update(conn, store, task_id, branch_name=str(branch_name))
