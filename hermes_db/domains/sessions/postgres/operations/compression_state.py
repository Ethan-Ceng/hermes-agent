"""Durable cooldowns and conservative recovery, under the lineage fence."""

import time

from sqlalchemy import case, select

from hermes_db.domains.sessions.postgres.queries import leases, sessions
from hermes_db.tables.conversations import messages, sessions as table
from hermes_db.tables.gateway import compression_locks
from hermes_db.core.values import decode_text, encode_text, explicit_fork


def lineage(conn, scope, session_id):
    from hermes_db.domains.sessions.postgres.queries.messages import resume_lineage
    if sessions.raw_session(conn, scope, session_id) is None:
        return []
    result = [resume_lineage(conn, scope, session_id)[0]]
    while True:
        found = children(conn, scope, result[-1])
        if not found:
            return result
        child = found[0]["id"]
        if child in result:
            raise RuntimeError("Compression lineage contains a cycle")
        result.append(child)


def cooldown_row(conn, scope, session_id):
    row = sessions.raw_session(conn, scope, session_id)
    return {"session_exists": row is not None,
            "cooldown_until": row["compression_failure_cooldown_until"] if row else None,
            "error": decode_text(row["compression_failure_error"]) if row else None}


def record_cooldown(conn, scope, session_id, deadline, error):
    if sessions.lock_session(conn, scope, session_id) is None:
        return
    current = table.c.compression_failure_cooldown_until
    sessions.update_session(conn, scope, session_id, {
        "compression_failure_cooldown_until": case((current > deadline, current), else_=deadline),
        "compression_failure_error": encode_text(error)})


def restore_cooldown(conn, scope, session_id, snapshot):
    row = sessions.lock_session(conn, scope, session_id)
    if not snapshot.get("session_exists", False):
        if row is not None:
            raise RuntimeError("cannot restore absent compression cooldown row: session now exists")
        return
    if row is not None:
        sessions.update_session(conn, scope, session_id, {
            "compression_failure_cooldown_until": snapshot.get("cooldown_until"),
            "compression_failure_error": encode_text(snapshot.get("error"))})


def children(conn, scope, parent_id, *, live_only=False):
    conditions = [sessions.where_session(scope, parent_id)]
    parent = conn.execute(select(table.c.end_reason).where(*conditions)).scalar_one_or_none()
    if parent != "compression":
        return []
    conditions = [table.c.store_id == scope.require_store_id(), table.c.parent_session_id == parent_id]
    if live_only:
        conditions.append(table.c.ended_at.is_(None))
    rows = conn.execute(select(table).where(*conditions).order_by(table.c.started_at, table.c.id)).mappings()
    return [dict(row) for row in rows if not explicit_fork(row)]


def reopen(conn, scope, session_id, *, orphan=False):
    from hermes_state_common import _BOUNDARY_END_REASONS, is_automatic_end_reason

    sessions.lock_store(conn, scope, exclusive=True)
    row = sessions.lock_session(conn, scope, session_id)
    if row is None or row["ended_at"] is None:
        return False if orphan else None
    reason = row["end_reason"]
    if orphan:
        if reason != "compression" or children(conn, scope, session_id):
            return False
        conditions = leases.where(scope, compression_locks, "session_id", session_id)
        lock = conn.execute(select(compression_locks).where(*conditions).with_for_update()).mappings().one_or_none()
        if lock:
            if lock["expires_at"] >= time.time():
                return False
            leases.release(conn, scope, compression_locks, "session_id", session_id, lock["holder"])
    elif (reason == "compression" or reason in _BOUNDARY_END_REASONS or is_automatic_end_reason(reason)
          or _any_continuation(conn, scope, session_id)):
        return None
    sessions.update_session(conn, scope, session_id, {"ended_at": None, "end_reason": None})
    return True if orphan else str(reason)


def _any_continuation(conn, scope, session_id):
    rows = conn.execute(select(table).where(table.c.store_id == scope.require_store_id(),
        table.c.parent_session_id == session_id)).mappings()
    return any(not explicit_fork(row) for row in rows)


def finalize_orphans(conn, scope):
    sessions.lock_store(conn, scope, exclusive=True)
    parent = table.alias("parent")
    has_messages = select(messages.c.id).where(messages.c.store_id == table.c.store_id,
        messages.c.session_id == table.c.id).exists()
    has_parent = select(parent.c.id).where(parent.c.store_id == table.c.store_id,
        parent.c.id == table.c.parent_session_id, parent.c.end_reason == "compression", parent.c.ended_at.is_not(None)).exists()
    conditions = (table.c.store_id == scope.require_store_id(), table.c.api_call_count == 0,
        table.c.end_reason.is_(None), table.c.ended_at.is_(None), table.c.started_at < time.time() - 604800,
        has_messages, has_parent)
    roots = conn.execute(select(table.c.lineage_root_id).where(*conditions).distinct()).scalars()
    for root in sorted(roots):
        sessions.lock_root(conn, scope, root)
    return conn.execute(table.update().where(*conditions).values(
        ended_at=time.time(), end_reason="orphaned_compression")).rowcount
