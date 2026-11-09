"""Sweep candidates are checked and retired on the same mapping/root fence."""

from sqlalchemy import select
import time

from hermes_db.domains.sessions.postgres.operations import retirement, retirement_guards as guards
from hermes_db.domains.sessions.postgres.queries import gateway, gateway_peers, retirement as targets, retirement_housekeeping as repo, sessions
from hermes_db.tables.conversations import messages, sessions as table
from hermes_db.tables.runtime import session_admissions, worker_executions
from hermes_db.domains.runtime.values import RuntimeStoreError


def prunable(conn, scope, session_ids, *, media_references):
    swept, (members, derived) = set(session_ids), repo.conversations(conn, scope)
    guards.lock_targets(conn, scope, session_ids)
    quiet = []
    for sid in session_ids:
        whole = members.get(sid, (sid,))
        if not swept.issuperset(whole):
            continue
        protected = targets.compression_members(conn, scope, whole)
        if guards.guarded_ids(conn, scope, protected):
            continue
        try:
            guards.require_quiet(conn, scope, protected)
        except RuntimeStoreError as error:
            if error.reason not in ("session_busy", "unknown_execution"):
                raise
            continue
        quiet.append(sid)
    derived |= repo.derived_api(conn, scope, quiet)
    retirement.retire_sessions(conn, scope, quiet, expiring=set(quiet) - derived, media_references=media_references)
    return quiet


def _has_messages(scope):
    return select(messages.c.id).where(messages.c.store_id == scope.require_store_id(), messages.c.session_id == table.c.id).exists()


def delete_empty(conn, scope, *, media_references):
    sessions.lock_store(conn, scope, exclusive=True)
    ids = list(conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(), table.c.message_count == 0,
        table.c.ended_at.is_not(None), table.c.archived == 0, ~_has_messages(scope))).scalars())
    ids = prunable(conn, scope, ids, media_references=media_references)
    retirement.delete_rows(conn, scope, ids)
    repo.prune(conn, scope)
    return ids


def prune_ghosts(conn, scope, *, media_references):
    sessions.lock_store(conn, scope, exclusive=True)
    ids = conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
        table.c.source == "tui", table.c.title.is_(None), table.c.ended_at.is_not(None),
        table.c.started_at < time.time() - 86400, ~_has_messages(scope))).scalars().all()
    ids = prunable(conn, scope, ids, media_references=media_references)
    retirement.delete_rows(conn, scope, ids)
    return ids


def delete_if_empty(conn, scope, session_id, *, media_references):
    sessions.lock_store(conn, scope, exclusive=True)
    row = sessions.lock_session(conn, scope, session_id)
    if row is None or row["title"] is not None or guards.guarded_ids(conn, scope, [session_id]) or targets.local_members(conn, scope, session_id) != [session_id]:
        return False
    child = conn.scalar(select(table.c.id).where(table.c.store_id == scope.require_store_id(), table.c.parent_session_id == session_id).limit(1))
    message = conn.scalar(select(messages.c.id).where(messages.c.store_id == scope.require_store_id(), messages.c.session_id == session_id).limit(1))
    if child is not None or message is not None:
        return False
    retirement.retire_sessions(conn, scope, [session_id], expiring=[session_id], media_references=media_references)
    retirement.delete_rows(conn, scope, [session_id])
    return True


def discard_unadmitted(conn, scope, session_id, *, media_references):
    sessions.lock_store(conn, scope, exclusive=True)
    if sessions.lock_session(conn, scope, session_id) is None:
        return False, []
    admission = conn.scalar(select(session_admissions.c.admission_id).where(
        session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.target_session_id == session_id).limit(1))
    worker = conn.scalar(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id == session_id).limit(1))
    if admission is not None or worker is not None:
        return retirement.delete_one(conn, scope, session_id, media_references=media_references)
    retirement.delete_rows(conn, scope, [session_id])
    return True, []


def never_active(conn, scope, older_than_days, *, media_references):
    sessions.lock_store(conn, scope, exclusive=True)
    ids = sorted(row["id"] for row in gateway_peers.never_active(conn, scope, older_than_days)
        if targets.local_members(conn, scope, row["id"]) == [row["id"]])
    if not ids:
        return 0, [], [], 0, []
    routed = [row for row in gateway.routing_rows(conn, scope) if gateway.entry_session_id(row["entry_json"]) in ids]
    count, removed, skipped = retirement.delete_many(conn, scope, ids, exclude_active_write_guards=True, media_references=media_references)
    routing_count = sum(gateway.entry_session_id(row["entry_json"]) not in skipped for row in routed)
    return count, removed, skipped, routing_count, [sid for sid in ids if sid not in skipped]
