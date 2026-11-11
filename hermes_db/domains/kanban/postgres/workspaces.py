"""Kanban workspaces workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
from sqlalchemy import and_, or_, select, update, delete
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban import tasks, links
from hermes_db.core.values import encode_text
import json
from uuid import uuid4
from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageError, StorageBusyError
from hermes_db.tables.kanban_workspaces import paths, references
from sqlalchemy.dialects.postgresql import insert
TERMINAL = (b'done', b'archived', b'failed', b'cancelled')



def _has_active_children(store, task_id):
    query = select(tasks.c.id).join(links, and_(tasks.c.store_id == links.c.store_id, tasks.c.board_id == links.c.board_id, tasks.c.id == links.c.child_id))
    with store.read() as conn:
        return conn.scalar(query.where(repo.scope(tasks, store), links.c.parent_id == encode_text(task_id), tasks.c.status.not_in(TERMINAL)).limit(1)) is not None

def _is_terminal_task(store, task_id):
    with store.read() as conn:
        return conn.scalar(select(tasks.c.id).where(repo.key(store, task_id), tasks.c.status.in_(TERMINAL))) is not None



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



def _finish(store, path_key, token):
    with DomainResource.write(store) as conn:
        conn.execute(update(paths).where(path_scope(store, path_key), paths.c.cleanup_token == token).values(cleanup_token=None, cleanup_payload=None))


TERMINAL = (b'done', b'archived', b'failed', b'cancelled')


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


def other_workspace_paths(store, task_id):
    with store.read() as conn:
        return list(conn.scalars(select(tasks.c.workspace_path).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in(TERMINAL), tasks.c.workspace_path.is_not(None), or_(tasks.c.board_id != store.board_id, tasks.c.id != encode_text(task_id)))))


def set_workspace_reference(conn, store, task_id, path, key):
    repo.require_task(conn, store, task_id)
    register(conn, store, task_id, key)
    repo.task_update(conn, store, task_id, workspace_path=str(path))


def cleanup_candidate(store, task_id):
    with store.read() as conn:
        return repo.get(conn, store, task_id)


def require_cleanup_reservation(conn, store, task, path_key, token):
    from hermes_db.domains.kanban.postgres.files import lock_files
    lock_files(conn, store)
    current = conn.scalar(select(paths.c.cleanup_token).where(path_scope(store, path_key)).with_for_update())
    if current != token:
        return False
    if live_references(conn, store, path_key) is not None or _active_children(conn, store, task['id']):
        raise StorageBusyError('Captured cleanup still has live workspace users')
    return True
