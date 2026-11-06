"""Terminal worker cleanup used by admission settlement and owner recovery."""

import json
import time

from sqlalchemy import select

from hermes_db.repositories import sessions
from hermes_db.repositories.session_queries import json_key_exists
from hermes_db.tables.runtime import worker_executions, worker_receipts
from hermes_state_runtime_workers import CHILD_SEPARATOR, RETIRED_RECEIPT, descendant_range


def compact(conn, scope, execution_id):
    conn.execute(worker_receipts.update().where(worker_receipts.c.store_id == scope.require_store_id(),
        worker_receipts.c.execution_id == execution_id,
        (json_key_exists(conn, worker_receipts.c.result_json, "messages") |
         json_key_exists(conn, worker_receipts.c.result_json, "session")))
        .values(result_json=json.dumps(RETIRED_RECEIPT)))


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
    low, high = descendant_range(execution_id)
    rows = conn.execute(select(worker_executions.c.execution_id, worker_executions.c.session_id).where(
        worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.execution_id >= low,
        worker_executions.c.execution_id < high, worker_executions.c.status != "terminal")).mappings().all()
    _retire_children(conn, scope, rows)
    compact(conn, scope, execution_id)
    if CHILD_SEPARATOR in execution_id:
        row = conn.execute(select(worker_executions.c.execution_id, worker_executions.c.session_id).where(
            worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.execution_id == execution_id)).mappings().one()
        _retire_children(conn, scope, [row])
