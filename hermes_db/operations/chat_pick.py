"""Messaging pick receipts recheck mount fences after edge-side preparation."""

from hermes_db.domains.sessions.postgres.operations.mutations import replay_receipt, save_receipt
from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table
from hermes_state_runtime import RuntimeStoreError


def _fenced(conn, scope, session_id, params):
    row = sessions.get_session(conn, scope, session_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    if row["runtime_revision"] != params["expected_revision"]:
        raise RuntimeStoreError("revision_conflict")
    if row["runtime_generation"] != params["expected_generation"]:
        raise RuntimeStoreError("stale_generation")
    return row


def prepare(conn, scope, *, epoch, key, digest, session_id, params):
    runtime.require_epoch(conn, scope, epoch)
    replay = replay_receipt(conn, scope, key, digest)
    return {"receipt": replay} if replay is not None else {"row": _fenced(conn, scope, session_id, params)}


def commit(conn, scope, *, epoch, key, digest, session_id, params, result):
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    replay = replay_receipt(conn, scope, key, digest)
    if replay is not None:
        return replay
    sessions.lock_session(conn, scope, session_id)
    _fenced(conn, scope, session_id, params)
    sessions.update_session(conn, scope, session_id, {"runtime_revision": table.c.runtime_revision + 1})
    committed = {**result, "revision": sessions.raw_session(conn, scope, session_id)["runtime_revision"]}
    save_receipt(conn, scope, key, digest, committed)
    return committed
