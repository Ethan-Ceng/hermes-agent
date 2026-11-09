"""Reference changes and cleanup serialize on the same store/path row."""

import os
from pathlib import Path
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.errors import StorageBusyError
from hermes_db.tables.kanban import tasks, links
from hermes_db.tables.kanban_workspaces import paths, references
from hermes_db.core.values import encode_text

TERMINAL = (b"done", b"archived", b"failed", b"cancelled")


def canonical_path(path):
    from hermes_cli.kanban_db_workspace import _path_key
    return os.path.normcase(_path_key(Path(path).expanduser().resolve(strict=False))) if path else None


def path_scope(store, key):
    return and_(paths.c.store_id == store.scope.require_store_id(), paths.c.path_key == encode_text(key))


def reference_scope(store, task_id):
    return and_(references.c.store_id == store.scope.require_store_id(), references.c.board_id == store.board_id,
                references.c.task_id == encode_text(task_id))


def lock_path(conn, store, key):
    from hermes_db.operations.kanban_file_jobs import guard_reference
    guard_reference(conn, store, key)
    conn.execute(insert(paths).values(store_id=store.scope.require_store_id(), path_key=encode_text(key)).on_conflict_do_nothing())
    token = conn.scalar(select(paths.c.cleanup_token).where(path_scope(store, key)).with_for_update())
    if token is not None:
        raise StorageBusyError("Workspace cleanup is pending; retain the workspace and retry after reconciliation")


def register(conn, store, task_id, key):
    if key is None:
        conn.execute(delete(references).where(reference_scope(store, task_id)))
        return
    lock_path(conn, store, key)
    conn.execute(insert(references).values(store_id=store.scope.require_store_id(), board_id=store.board_id,
        task_id=encode_text(task_id), path_key=encode_text(key)).on_conflict_do_update(
            index_elements=[references.c.store_id, references.c.board_id, references.c.task_id],
            set_={"path_key": encode_text(key)}))


def key_for_task(conn, store, task_id):
    from hermes_db.core.values import decode_text
    return decode_text(conn.scalar(select(references.c.path_key).where(reference_scope(store, task_id))))


def guard_live_task(conn, store, task_id):
    from hermes_db.core.values import decode_text
    parent_ids = select(links.c.parent_id).where(links.c.store_id == store.scope.require_store_id(),
        links.c.board_id == store.board_id, links.c.child_id == encode_text(task_id))
    keys = conn.scalars(select(references.c.path_key).where(references.c.store_id == store.scope.require_store_id(),
        references.c.board_id == store.board_id,
        or_(references.c.task_id == encode_text(task_id), references.c.task_id.in_(parent_ids))).distinct().order_by(references.c.path_key))
    for key in list(keys):
        lock_path(conn, store, decode_text(key))


def guard_parent_link(conn, store, parent_id, child_id):
    from hermes_db.repositories.kanban import key
    status = conn.scalar(select(tasks.c.status).where(key(store, child_id)))
    path = key_for_task(conn, store, parent_id)
    if path is not None and status not in TERMINAL:
        lock_path(conn, store, path)


def live_references(conn, store, path_key):
    own = and_(tasks.c.store_id == references.c.store_id, tasks.c.board_id == references.c.board_id,
               tasks.c.id == references.c.task_id)
    live = conn.scalar(select(tasks.c.id).join(references, own).where(tasks.c.store_id == store.scope.require_store_id(),
        tasks.c.status.not_in(TERMINAL), references.c.path_key == encode_text(path_key)).limit(1))
    if live is not None:
        return "shared"
    # An upgrade cannot resolve old local paths in SQL. Preserve until explicit reconciliation.
    missing = conn.scalar(select(tasks.c.id).outerjoin(references, own).where(
        tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL),
        tasks.c.workspace_path.is_not(None), references.c.task_id.is_(None)).limit(1))
    return "unknown" if missing is not None else None
