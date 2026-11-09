"""Whole native deletion transaction: guards, terminal evidence, fences, body."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import retirement_guards as guards
from hermes_db.domains.sessions.postgres.queries import prompts, retirement as repo, retirement_fences as fences, retirement_ledger as ledger, sessions
from hermes_db.tables.conversations import messages, sessions as table


def retire_sessions(conn, scope, session_ids, *, expiring=()):
    from hermes_db.domains.sessions.postgres.queries import media
    guards.require_quiet(conn, scope, session_ids)
    media.retire_spillover(conn, scope, list(session_ids))
    ledger.retire(conn, scope, session_ids)
    fences.retire_mutations(conn, scope, session_ids)
    fences.retire_routes(conn, scope, session_ids, expiring=expiring)
    fences.retire_local(conn, scope, session_ids)


def delete_rows(conn, scope, session_ids):
    orphans = list(conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
        table.c.parent_session_id.in_(session_ids), table.c.id.not_in(session_ids))).scalars())
    conn.execute(table.update().where(table.c.store_id == scope.require_store_id(),
        table.c.parent_session_id.in_(session_ids)).values(parent_session_id=None))
    conn.execute(messages.delete().where(messages.c.store_id == scope.require_store_id(), messages.c.session_id.in_(session_ids)))
    conn.execute(table.delete().where(table.c.store_id == scope.require_store_id(), table.c.id.in_(session_ids)))
    _rebase_orphans(conn, scope, orphans)
    prompts.prune_prompts(conn, scope)


def _rebase_orphans(conn, scope, orphan_ids):
    # Explicit physical deletion severs these conversations. Their old root
    # rows remain durable lock targets, but surviving components get their own
    # map/lease key just as a new root does; independent siblings cannot share flags.
    for sid in sorted(orphan_ids):
        sessions.create_root(conn, scope, sid)
        sessions.lock_root(conn, scope, sid)
    for sid in sorted(orphan_ids):
        members = repo.compression_members(conn, scope, [sid])
        conn.execute(table.update().where(table.c.store_id == scope.require_store_id(), table.c.id.in_(members))
            .values(lineage_root_id=sid))


def delete_one(conn, scope, session_id, *, expected_delete_ids=None, expected_display_messages=None,
               exclude_active_write_guards=False):
    from hermes_state_errors import SessionActiveWriteGuardError

    sessions.lock_store(conn, scope, exclusive=True)
    if sessions.raw_session(conn, scope, session_id) is None:
        return False, []
    targets = repo.expand_native(conn, scope, session_id)
    guards.lock_targets(conn, scope, targets)
    if exclude_active_write_guards and guards.guarded_ids(conn, scope, targets):
        raise SessionActiveWriteGuardError("Session or a delegate child holds an active write lease")
    if expected_delete_ids is not None and set(expected_delete_ids) != set(targets):
        return False, []
    if expected_display_messages is not None and any(repo.display_snapshot(conn, scope, sid) != expected
            for sid, expected in expected_display_messages.items()):
        return False, []
    retire_sessions(conn, scope, targets)
    delete_rows(conn, scope, targets)
    return True, targets


def delete_many(conn, scope, session_ids, *, exclude_active_write_guards=False, include_compression_chain=False):
    requested = sorted({sid for sid in session_ids or () if isinstance(sid, str) and sid})
    if not requested:
        return 0, [], []
    sessions.lock_store(conn, scope, exclusive=True)
    existing = list(conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(), table.c.id.in_(requested))).scalars())
    closures = {sid: repo.expand_native(conn, scope, sid, compression=include_compression_chain) for sid in existing}
    targets = sorted({sid for closure in closures.values() for sid in closure})
    guards.lock_targets(conn, scope, targets)
    leased = guards.guarded_ids(conn, scope, targets) if exclude_active_write_guards else set()
    skipped = sorted(sid for sid, closure in closures.items() if leased.intersection(closure))
    kept = {sid: closure for sid, closure in closures.items() if sid not in skipped}
    targets = sorted({sid for closure in kept.values() for sid in closure})
    if targets:
        retire_sessions(conn, scope, targets)
        delete_rows(conn, scope, targets)
    return len(kept), targets, skipped
