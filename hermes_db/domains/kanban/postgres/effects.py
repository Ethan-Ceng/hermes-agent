"""Kanban effects workflow; original connection, fence and off-connection effect boundaries are preserved."""
import logging
_kanban_logger = logging.getLogger("hermes_cli.kanban_db")
import json
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import delete, func, or_, select, update
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.core.resource import DomainResource
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban import kanban_boards
from hermes_db.tables.kanban_effects import effects
from hermes_db.core.values import encode_text

def enqueue(conn, store, steps):
    effect_id = uuid4().hex
    conn.execute(effects.insert().values(**repo.owner(store), effect_id=effect_id, owner_home=encode_text(str(store.scope.profile_home)), payload=json.dumps(steps, ensure_ascii=True).encode()))
    return effect_id

def hook_step(store, task, event, run_id, **fields):
    return {'kind': 'hook', 'event': event, 'task_id': task['id'], 'assignee': task['assignee'], 'board': store.slug, 'run_id': run_id, 'fields': fields}

def _key(resource, row):
    return (effects.c.store_id == resource.scope.require_store_id()) & (effects.c.board_id == row['board_id']) & (effects.c.effect_id == row['effect_id'])

def _claim(resource, effect_id):
    stamp = func.extract('epoch', func.clock_timestamp())
    with DomainResource.write(resource) as conn:
        query = select(effects).where(effects.c.store_id == resource.scope.require_store_id(), effects.c.owner_home == encode_text(str(resource.scope.profile_home)), or_(effects.c.claim.is_(None), effects.c.expires_at <= stamp))
        if effect_id is not None:
            query = query.where(effects.c.effect_id == effect_id)
        row = conn.execute(query.with_for_update(skip_locked=True).limit(1)).mappings().one_or_none()
        if row is None:
            return None
        row = dict(row, claim=uuid4().hex)
        conn.execute(update(effects).where(_key(resource, row)).values(claim=row['claim'], expires_at=stamp + 300))
        return row

def _invoke(store, step):

    handlers = {'ready': lambda: store.recompute_ready(), 'workspace': lambda: store._cleanup_workspace(step['task_id']), 'phantom': lambda: store._flag_phantom_prose_refs(step['task_id'], step['run_id'], step['summary'], step['result'], step['verified']), 'hook': lambda: store.observers.fire_task_hook(step['event'], SimpleNamespace(assignee=step['assignee']), step['task_id'], step['run_id'], board=step['board'], **step['fields'])}
    handlers[step['kind']]()

def _run(resource, row):
    from hermes_db.errors import StorageBusyError
    with resource.read() as conn:
        slug, archived = conn.execute(select(kanban_boards.c.slug, kanban_boards.c.archived).where(kanban_boards.c.store_id == resource.scope.require_store_id(), kanban_boards.c.board_id == row['board_id'])).one()
    steps = json.loads(bytes(row['payload']))
    with BoardResource(resource, row['board_id'], slug) as board, board._operation_scope():
        for phase in range(row['phase'], len(steps)):
            with DomainResource.write(resource) as conn:
                changed = conn.execute(update(effects).where(_key(resource, row), effects.c.claim == row['claim']).values(expires_at=func.extract('epoch', func.clock_timestamp()) + 300)).rowcount
            if changed != 1:
                raise StorageBusyError('Kanban post-commit effect claim changed')
            if not (archived and steps[phase]['kind'] in ('ready', 'phantom')):
                _invoke(board, steps[phase])
            with DomainResource.write(resource) as conn:
                conn.execute(update(effects).where(_key(resource, row), effects.c.claim == row['claim']).values(phase=phase + 1))
    with DomainResource.write(resource) as conn:
        conn.execute(delete(effects).where(_key(resource, row), effects.c.claim == row['claim']))

def drain(resource, effect_id=None, *, limit=100):
    for _ in range(limit):
        row = _claim(resource, effect_id)
        if row is None:
            return
        _run(resource, row)

def after_commit(store, effect_id):
    from hermes_db.errors import StorageError

    try:
        drain(store, effect_id, limit=1)
    except (StorageError, OSError) as error:
        _kanban_logger.warning('Kanban post-commit work remains pending (%s)', type(error).__name__)
