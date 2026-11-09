"""Runtime/lease refusals on the connection holding every deletion root."""

import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.gateway import compression_locks, session_turn_leases
from hermes_db.tables.runtime import session_admissions, worker_executions
from hermes_db.domains.runtime.values import RuntimeStoreError


def require_quiet(conn, scope, session_ids, *, allow_queued=False):
    statuses = ("started", "unknown") if allow_queued else ("queued", "started", "unknown")
    states = set(conn.execute(select(session_admissions.c.status).where(
        session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.target_session_id.in_(session_ids),
        session_admissions.c.status.in_(statuses))).scalars())
    states.update(conn.execute(select(worker_executions.c.status).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(session_ids), worker_executions.c.status.in_(("registered", "running", "unknown")))).scalars())
    if "unknown" in states:
        raise RuntimeStoreError("unknown_execution")
    if states:
        raise RuntimeStoreError("session_busy")


def lock_targets(conn, scope, session_ids):
    sessions.lock_store(conn, scope, exclusive=True)
    roots = conn.execute(select(table.c.lineage_root_id).where(table.c.store_id == scope.require_store_id(),
        table.c.id.in_(session_ids)).distinct()).scalars().all()
    for root in sorted(roots):
        sessions.lock_root(conn, scope, root)


def require_unleased(conn, scope, session_ids, *, allow_queued=False):
    from hermes_db.domains.sessions.postgres.operations import transcript_guards

    require_quiet(conn, scope, session_ids, allow_queued=allow_queued)
    for sid in session_ids:
        row = sessions.raw_session(conn, scope, sid)
        if row and row["end_reason"] != "compression":
            transcript_guards.check(conn, scope, sid, reject_active_turn_lease=True, reject_active_compression_lock=True)


def guarded_ids(conn, scope, session_ids):
    rows = conn.execute(select(table.c.id, table.c.lineage_root_id).where(table.c.store_id == scope.require_store_id(),
        table.c.id.in_(session_ids))).mappings().all()
    now = time.time()
    compression = set(conn.execute(select(compression_locks.c.session_id).where(
        compression_locks.c.store_id == scope.require_store_id(), compression_locks.c.session_id.in_(session_ids),
        compression_locks.c.expires_at >= now)).scalars())
    roots = {row["lineage_root_id"] for row in rows}
    leased = set(conn.execute(select(session_turn_leases.c.conversation_id).where(
        session_turn_leases.c.store_id == scope.require_store_id(), session_turn_leases.c.conversation_id.in_(roots),
        session_turn_leases.c.expires_at > now)).scalars())
    return compression | {row["id"] for row in rows if row["lineage_root_id"] in leased}
