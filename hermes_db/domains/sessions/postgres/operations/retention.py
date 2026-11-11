"""Atomic bulk archive/prune under the mapping fence and sorted root locks."""

import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import housekeeping, retirement, retirement_guards, sessions as session_ops, titles
from hermes_db.domains.sessions.postgres.queries import retention, retirement_housekeeping, sessions
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.domains.sessions.postgres.queries import session_queries
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.gateway import gateway_heartbeats
from hermes_db.core.values import encode_text
from hermes_db.domains.runtime.values import RuntimeStoreError


def archive(conn, scope, older_than_days, source, filters, *, automatic=False):
    sessions.lock_store(conn, scope, exclusive=True)
    rows = retention.candidates(conn, scope, older_than_days, source, **filters)
    if automatic:
        canonical = conn.scalar(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
            table.c.hidden != 0, table.c.title == encode_text(titles.BOT_TITLE)))
        rows = [row for row in rows if row["id"] != canonical]
    retirement_guards.lock_targets(conn, scope, [row["id"] for row in rows])
    events = []
    for row in rows:
        ids = session_ops.lineage_flag(conn, scope, row["id"], "archived", 1, extra={"auto_archived": int(automatic)})
        if not row["archived"]:
            events.append((row["id"], ids))
    return len(rows), events


def prune(conn, scope, older_than_days, source, filters, *, exclude_active_write_guards=False, media_references, retire_spillover):
    sessions.lock_store(conn, scope, exclusive=True)
    rows = retention.candidates(conn, scope, older_than_days, source, whole_lineages=True, **filters)
    ids = [row["id"] for row in rows]
    if exclude_active_write_guards:
        guarded = retirement_guards.guarded_ids(conn, scope, ids)
        ids = [sid for sid in ids if sid not in guarded]
    ids = housekeeping.prunable(conn, scope, ids, media_references=media_references, retire_spillover=retire_spillover)
    if ids:
        retirement.delete_rows(conn, scope, ids)
    retirement_housekeeping.prune(conn, scope)
    return ids


def stale_archive(conn, scope, idle_days, exclude_pinned):
    return archive(conn, scope, idle_days, None, dict(include_open=True, archived=False,
        lineage_tips_only=True, include_pinned=not exclude_pinned), automatic=True)


def throttled_archive(conn, scope, idle_days, exclude_pinned, interval_hours):
    sessions.lock_store(conn, scope, exclusive=True)
    now = time.time()
    if not _due(runtime.meta(conn, scope, "last_auto_archive"), now, interval_hours):
        return {"skipped": True, "archived": 0}, []
    count, events = stale_archive(conn, scope, idle_days, exclude_pinned) if idle_days is not None and idle_days >= 0 else (0, [])
    runtime.set_meta(conn, scope, "last_auto_archive", str(now))
    return {"skipped": False, "archived": count}, events


def _due(raw, now, hours):
    try:
        last = float(raw or 0)
    except (TypeError, ValueError):
        last = 0
    return not last or now - last >= hours * 3600


def _quiet_ids(conn, scope, ids):
    retirement_guards.lock_targets(conn, scope, ids)
    quiet = []
    from hermes_db.domains.sessions.postgres.queries.retirement import compression_members
    for sid in ids:
        members = compression_members(conn, scope, [sid])
        if retirement_guards.guarded_ids(conn, scope, members):
            continue
        try:
            retirement_guards.require_unleased(conn, scope, members)
        except RuntimeStoreError as error:
            if error.reason not in ("session_busy", "unknown_execution"):
                raise
            continue
        quiet.append(sid)
    return quiet


def sweep_orphans(conn, scope, *, max_idle_seconds, sources=("tui", "desktop", "subagent"), exclude_ids=(),
                  exclude_pinned=False, heartbeat_staleness_seconds=None, heartbeat_ownership_grace_seconds=None,
                  respect_gateway_heartbeats=True):
    sources = tuple(source for source in sources if source)
    if max_idle_seconds <= 0 or not sources:
        return []
    sessions.lock_store(conn, scope, exclusive=True)
    now, cutoff = time.time(), time.time() - max_idle_seconds
    clauses = [table.c.store_id == scope.require_store_id(), table.c.ended_at.is_(None), table.c.source.in_(sources),
        table.c.started_at < cutoff, session_queries.last_activity(conn) < cutoff]
    if exclude_ids:
        clauses.append(table.c.id.not_in([str(value) for value in exclude_ids if value]))
    if exclude_pinned:
        clauses.append(retention.not_pinned())
    if respect_gateway_heartbeats:
        staleness = heartbeat_staleness_seconds if heartbeat_staleness_seconds and heartbeat_staleness_seconds > 0 else max_idle_seconds * 2
        grace = heartbeat_ownership_grace_seconds if heartbeat_ownership_grace_seconds is not None and heartbeat_ownership_grace_seconds >= 0 else staleness
        clauses.append(~select(gateway_heartbeats.c.backend_id).where(gateway_heartbeats.c.store_id == scope.require_store_id(),
            gateway_heartbeats.c.last_heartbeat >= now - staleness, gateway_heartbeats.c.started_at <= table.c.started_at + grace).correlate(table).exists())
    candidates = conn.execute(select(table.c.id).where(*clauses).order_by(table.c.id)).scalars().all()
    quiet = _quiet_ids(conn, scope, candidates)
    if quiet:
        conn.execute(table.update().where(*clauses, table.c.id.in_(quiet)).values(ended_at=now, end_reason="startup_orphan_reap"))
    return quiet


def auto_prune(conn, scope, retention_days, min_interval_hours, *, media_references, retire_spillover):
    from hermes_db.domains.sessions.rules import AUTO_PRUNE_STALE_OPEN_SOURCES
    sessions.lock_store(conn, scope, exclusive=True)
    now = time.time()
    if not _due(runtime.meta(conn, scope, "last_auto_prune"), now, min_interval_hours):
        return {"skipped": True, "pruned": 0, "closed": 0, "vacuumed": False}, []
    removed = prune(conn, scope, retention_days, None, {}, exclude_active_write_guards=True, media_references=media_references, retire_spillover=retire_spillover)
    closed = sweep_orphans(conn, scope, max_idle_seconds=float(retention_days) * 86400,
        sources=AUTO_PRUNE_STALE_OPEN_SOURCES, exclude_pinned=True, respect_gateway_heartbeats=False)
    runtime.set_meta(conn, scope, "last_auto_prune", str(now))
    return {"skipped": False, "pruned": len(removed), "closed": len(closed), "vacuumed": False}, removed
