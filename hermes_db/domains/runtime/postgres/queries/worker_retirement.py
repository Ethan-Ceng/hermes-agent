"""Terminal worker cleanup used by admission settlement and owner recovery."""

import json
import time

from sqlalchemy import and_, func, select

from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.runtime import worker_executions, worker_receipts
from hermes_state_runtime_workers import CHILD_SEPARATOR, RETIRED_RECEIPT


def compact(conn, scope, execution_id):
    conn.execute(worker_receipts.update().where(worker_receipts.c.store_id == scope.require_store_id(),
        worker_receipts.c.execution_id == execution_id,
        worker_receipts.c.read_snapshot == 1).values(result_json=json.dumps(RETIRED_RECEIPT), read_snapshot=0))


def _retire_children(conn, scope, rows):
    from hermes_db.tables.conversations import sessions as session_table
    for row in rows:
        execution_id = row["execution_id"]
        conn.execute(worker_executions.update().where(worker_executions.c.store_id == scope.require_store_id(),
            worker_executions.c.execution_id == execution_id).values(status="terminal"))
        compact(conn, scope, execution_id)
        sessions.update_session(conn, scope, row["session_id"], {"ended_at": time.time(), "end_reason": "agent_close"},
                                session_table.c.ended_at.is_(None))


def retire_stale_children(conn, scope, epoch):
    rows = conn.execute(select(worker_executions.c.execution_id, worker_executions.c.session_id).where(
        worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.kind == "child",
        worker_executions.c.status != "terminal", worker_executions.c.owner_epoch != epoch)).mappings().all()
    _retire_children(conn, scope, rows)


def compact_terminal(conn, scope, execution_id):
    rows = conn.execute(select(worker_executions.c.execution_id, worker_executions.c.session_id).where(
        worker_executions.c.store_id == scope.require_store_id(), descendant_condition(execution_id),
        worker_executions.c.status != "terminal")).mappings().all()
    _retire_children(conn, scope, rows)
    compact(conn, scope, execution_id)
    if CHILD_SEPARATOR in execution_id:
        row = conn.execute(select(worker_executions.c.execution_id, worker_executions.c.session_id).where(
            worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.execution_id == execution_id)).mappings().one()
        _retire_children(conn, scope, [row])


def descendant_condition(execution_id):
    # Locale-dependent TEXT range bounds do not prove prefix membership on PG.
    prefix = execution_id + CHILD_SEPARATOR
    column = worker_executions.c.execution_id
    return and_(column.startswith(prefix, autoescape=True), func.substr(column, 1, len(prefix)) == prefix)


def discard_orphans_on_reset(conn, scope, session_ids):
    rows = conn.execute(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(session_ids), worker_executions.c.status == "unknown",
        ~worker_executions.c.execution_id.startswith("admission-worker:", autoescape=True))).scalars().all()
    for execution_id in rows:
        conn.execute(worker_executions.update().where(worker_executions.c.store_id == scope.require_store_id(),
            worker_executions.c.execution_id == execution_id).values(status="terminal"))
        compact_terminal(conn, scope, execution_id)
