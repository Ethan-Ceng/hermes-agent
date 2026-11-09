"""Current-attempt owner evidence, without retaining a connection during owner/OS probes."""

import json

from sqlalchemy import and_, select

from hermes_db.domains.kanban.routing.evidence import typed_owner_receipt
from hermes_db.domains.kanban.postgres.queries import kanban as repo
from hermes_db.tables.kanban import events, tasks
from hermes_db.core.values import decode_text, encode_text


def _current_payload(store, task_id, kind):
    same_run = and_(events.c.store_id == tasks.c.store_id, events.c.board_id == tasks.c.board_id,
                    events.c.task_id == tasks.c.id, events.c.run_id == tasks.c.current_run_id)
    statement = select(events.c.payload).select_from(tasks.join(events, same_run)).where(
        repo.key(store, task_id), events.c.kind == encode_text(kind)).order_by(events.c.id.desc()).limit(1)
    with store.read() as conn:
        row = conn.execute(statement).one_or_none()
    if row is None:
        return None
    try:
        payload = json.loads(decode_text(row.payload))
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _owner_receipt(store, task_id):
    return typed_owner_receipt(_current_payload(store, task_id, "owner_admitted"))


def _latest_run_event(store, task_id, kind):
    return _current_payload(store, task_id, kind) or {}


def _task_owner_state(store, task_id):
    with store.read() as conn:
        return repo.get(conn, store, task_id)
