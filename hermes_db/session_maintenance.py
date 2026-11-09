"""Retention previews and business maintenance, with post-commit events and files."""

import logging

from sqlalchemy import func, select

from hermes_db.integration.postgres.operations import maintenance
from hermes_db.repositories import retention
from hermes_db.tables.conversations import sessions

logger = logging.getLogger(__name__)


class SessionMaintenance:
    def list_prune_candidates(self, older_than_days=None, source=None, *, whole_lineages=False, **filters):
        with self._read() as conn:
            return retention.candidates(conn, self.scope, older_than_days, source, whole_lineages=whole_lineages, **filters)

    def count_prune_matches(self, older_than_days=None, source=None, *, pinned_only=False, **filters):
        if pinned_only:
            filters["include_pinned"] = True
        with self._read() as conn:
            clauses = retention.conditions(conn, self.scope, older_than_days, source, filters)
            if pinned_only:
                clauses.append(sessions.c.pinned != 0)
            return conn.scalar(select(func.count()).select_from(sessions).where(*clauses))

    def count_open_prune_matches(self, older_than_days=None, source=None, **filters):
        if filters.get("include_open"):
            return 0
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(sessions).where(
                *retention.conditions(conn, self.scope, older_than_days, source, filters, only_open=True)))

    def archive_sessions(self, older_than_days=None, source=None, **filters):
        filters.setdefault("archived", False)
        filters["lineage_tips_only"] = True
        with self._write() as conn:
            count, events = maintenance.archive(conn, self.scope, older_than_days, source, filters)
        self._emit_archives(events)
        return count

    def _emit_archives(self, events):
        from hermes_db.integration.events import emit_deleted
        for primary, ids in events:
            emit_deleted(self._profile, ids, reason="archive", primary=primary)

    def prune_sessions(self, older_than_days=90, source=None, sessions_dir=None, exclude_active_write_guards=False,
                       deleted_ids=None, **filters):
        if filters.get("include_open"):
            raise ValueError("prune_sessions never deletes open sessions")
        with self._write() as conn:
            removed = maintenance.prune(conn, self.scope, older_than_days, source, filters,
                exclude_active_write_guards=exclude_active_write_guards)
        if deleted_ids is not None:
            deleted_ids.extend(removed)
        if removed:
            self._after_session_delete(removed, reason="prune", sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return len(removed)

    def archive_stale_sessions(self, idle_days, *, exclude_pinned=True):
        if idle_days is None or idle_days < 0:
            return 0
        with self._write() as conn:
            count, events = maintenance.stale_archive(conn, self.scope, idle_days, exclude_pinned)
        self._emit_archives(events)
        return count

    def maybe_auto_archive(self, idle_days=3, min_interval_hours=24, exclude_pinned=True):
        try:
            with self._write() as conn:
                result, events = maintenance.throttled_archive(conn, self.scope, idle_days, exclude_pinned, min_interval_hours)
            self._emit_archives(events)
            return result
        except Exception as error:  # health: allow BLE001 -- automatic optional maintenance never fails startup
            logger.warning("PG auto-archive deferred (%s)", type(error).__name__)
            return {"skipped": False, "archived": 0, "error": type(error).__name__}

    def sweep_orphaned_sessions(self, **options):
        with self._write() as conn:
            return maintenance.sweep_orphans(conn, self.scope, **options)

    def maybe_auto_prune_and_vacuum(self, retention_days=90, min_interval_hours=24, vacuum=True, sessions_dir=None,
                                   min_vacuum_interval_days=30, min_vacuum_freelist_ratio=0.25):
        # PostgreSQL physical maintenance belongs to the managed instance. The
        # legacy arguments remain accepted; this operation only maintains data.
        if retention_days is None or retention_days < 0:
            return {"skipped": True, "pruned": 0, "closed": 0, "vacuumed": False}
        try:
            with self._write() as conn:
                result, removed = maintenance.auto_prune(conn, self.scope, retention_days, min_interval_hours)
            if removed:
                self._after_session_delete(removed, reason="prune", sessions_dir=sessions_dir)
            return result
        except Exception as error:  # health: allow BLE001 -- automatic optional maintenance never fails startup
            logger.warning("PG auto-prune deferred (%s)", type(error).__name__)
            return {"skipped": False, "pruned": 0, "closed": 0, "vacuumed": False, "error": type(error).__name__}
