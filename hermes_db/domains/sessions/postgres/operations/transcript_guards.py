"""Transcript guards after the common root lock; no process-local PID inference."""

import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.gateway import compression_locks, session_turn_leases


def check(conn, scope, session_id, compression_lock_holder=None, *, turn_lease_holder=None,
          turn_lease_ttl_seconds=300, reject_active_turn_lease=False, reject_active_compression_lock=False,
          allow_closed_compression_parent=False):
    from hermes_state_errors import CompressionSessionClosedError, SessionCompressionInProgressError, SessionTurnLeaseLostError

    row = sessions.lock_session(conn, scope, session_id)
    if row is None:
        from hermes_state_runtime import RuntimeStoreError
        raise RuntimeStoreError("not_found")
    now = time.time()
    if reject_active_compression_lock:
        condition = (compression_locks.c.store_id == scope.require_store_id(), compression_locks.c.session_id == session_id)
        lock = conn.execute(select(compression_locks).where(*condition).with_for_update()).mappings().one_or_none()
        if lock and lock["expires_at"] <= now:
            conn.execute(compression_locks.delete().where(*condition, compression_locks.c.holder == lock["holder"]))
        elif lock and lock["holder"] != compression_lock_holder:
            raise SessionCompressionInProgressError(f"Session {session_id!r} is being compressed by another writer")
    if turn_lease_holder or reject_active_turn_lease:
        _check_lease(conn, scope, row["lineage_root_id"], turn_lease_holder, turn_lease_ttl_seconds, now,
                     SessionTurnLeaseLostError)
    if row["end_reason"] == "compression" and not allow_closed_compression_parent:
        raise CompressionSessionClosedError(session_id)
    return row


def _check_lease(conn, scope, root_id, holder, ttl, now, error_type):
    table = session_turn_leases
    condition = (table.c.store_id == scope.require_store_id(), table.c.conversation_id == root_id)
    lease = conn.execute(select(table).where(*condition).with_for_update()).mappings().one_or_none()
    if holder:
        if lease is None or lease["holder"] != holder:
            raise error_type("Session turn lease lost; refusing transcript write")
        if lease["expires_at"] <= now:
            conn.execute(table.update().where(*condition, table.c.holder == holder)
                         .values(expires_at=now + max(0.1, float(ttl))))
    elif lease:
        if lease["expires_at"] > now:
            raise error_type("Session has an active turn lease; refusing transcript mutation")
        conn.execute(table.delete().where(*condition, table.c.holder == lease["holder"]))
