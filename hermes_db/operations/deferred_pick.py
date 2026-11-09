"""Current deferred model/reasoning receipts, committed without touching the running turn."""

import json

from hermes_db.domains.sessions.postgres.operations.mutations import replay_receipt, save_receipt
from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.runtime import state_meta
from hermes_state_mutation_prepared import DEFERRED_PICK_PREFIX
from hermes_state_runtime import _json


def defer(conn, scope, *, epoch, session_id, key, digest, operation, pick, shown):
    from gateway.session_deferred_pick import deferred_value
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope)
    replay = replay_receipt(conn, scope, key, digest)
    if replay is not None:
        return replay
    row = runtime.lock_target(conn, scope, session_id)
    raw = runtime.meta(conn, scope, DEFERRED_PICK_PREFIX + session_id)
    value, picked = deferred_value(json.loads(raw) if raw else {}, operation, pick, shown)
    result = {"session_id": session_id, "operation": operation, "status": "deferred", **picked,
        "revision": row["runtime_revision"], "execution_generation": row["runtime_generation"]}
    runtime.set_meta(conn, scope, DEFERRED_PICK_PREFIX + session_id, _json(value))
    save_receipt(conn, scope, key, digest, result)
    return result


def compare(conn, scope, *, key, expected, value):
    if not key.startswith(DEFERRED_PICK_PREFIX):
        raise ValueError("Expected a deferred-pick key")
    sessions.lock_store(conn, scope)
    statement = state_meta.delete() if value is None else state_meta.update().values(value=value)
    return conn.execute(statement.where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key == key, state_meta.c.value == expected)).rowcount > 0
