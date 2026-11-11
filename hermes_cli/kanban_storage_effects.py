"""Application-owned replay of the existing Kanban post-commit effect queue."""
import json
import logging
from types import SimpleNamespace
from hermes_db.domains.kanban.api import BoardResource
_kanban_logger = logging.getLogger("hermes_cli.kanban_db")

def _invoke(store, step):

    from hermes_cli.kanban_storage_workspaces import cleanup_workspace
    handlers = {'ready': lambda: store.recompute_ready(), 'workspace': lambda: cleanup_workspace(store, step['task_id']), 'phantom': lambda: store._flag_phantom_prose_refs(step['task_id'], step['run_id'], step['summary'], step['result'], step['verified']), 'hook': lambda: store.observers.fire_task_hook(step['event'], SimpleNamespace(assignee=step['assignee']), step['task_id'], step['run_id'], board=step['board'], **step['fields'])}
    handlers[step['kind']]()

def _run(resource, row):
    from hermes_db.errors import StorageBusyError
    from hermes_db.domains.kanban.postgres import effects as db
    slug, archived = db.effect_board_status(resource, row)
    steps = json.loads(bytes(row['payload']))
    with BoardResource(resource, row['board_id'], slug) as board, board._operation_scope():
        for phase in range(row['phase'], len(steps)):
            changed = db.refresh_effect_claim(resource, row)
            if changed != 1:
                raise StorageBusyError('Kanban post-commit effect claim changed')
            if not (archived and steps[phase]['kind'] in ('ready', 'phantom')):
                _invoke(board, steps[phase])
            db.advance_effect(resource, row, phase)
    db.finish_effect(resource, row)

def drain(resource, effect_id=None, *, limit=100):
    from hermes_db.domains.kanban.postgres.effects import _claim
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
