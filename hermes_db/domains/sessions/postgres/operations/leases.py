"""Scoped lease operations; no local PID can prove a shared PG holder dead."""

import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import leases, sessions
from hermes_db.tables.gateway import compression_locks, session_turn_leases


def lock_key(conn, scope, session_id, *, turn=False):
    sessions.lock_store(conn, scope)
    row = sessions.raw_session(conn, scope, session_id)
    root = row["lineage_root_id"] if row else session_id
    sessions.create_root(conn, scope, root)
    sessions.lock_root(conn, scope, root)
    return root if turn else session_id


def change(conn, scope, session_id, holder, action, *, turn=False, ttl_seconds=300, now=None):
    key = lock_key(conn, scope, session_id, turn=turn)
    table, column = (session_turn_leases, "conversation_id") if turn else (compression_locks, "session_id")
    now = time.time() if now is None else now
    expires = now + (max(0.1, float(ttl_seconds)) if turn else float(ttl_seconds))
    if action == "acquire":
        return leases.claim(conn, scope, table, column, key, holder, now, expires)[0]
    if action == "renew":
        return leases.renew(conn, scope, table, column, key, holder, expires)
    leases.release(conn, scope, table, column, key, holder)


def expiry(conn, scope, session_id, holder):
    row = sessions.raw_session(conn, scope, session_id)
    root = row["lineage_root_id"] if row else session_id
    return conn.scalar(select(session_turn_leases.c.expires_at).where(
        *leases.where(scope, session_turn_leases, "conversation_id", root), session_turn_leases.c.holder == holder))


def compression_holder(conn, scope, session_id):
    return conn.scalar(select(compression_locks.c.holder).where(
        *leases.where(scope, compression_locks, "session_id", session_id), compression_locks.c.expires_at >= time.time()))
