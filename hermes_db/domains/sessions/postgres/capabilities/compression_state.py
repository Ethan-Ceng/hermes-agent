"""Compression guard state persisted in the selected store."""

import time

from hermes_db.domains.sessions.postgres.operations import compression_state as state
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table


class SessionCompressionState:
    def get_compression_failure_cooldown_row(self, session_id):
        with self._read() as conn:
            return state.cooldown_row(conn, self.scope, session_id)

    def get_compression_failure_cooldown(self, session_id):
        row = self.get_compression_failure_cooldown_row(session_id)
        deadline, now = row["cooldown_until"], time.time()
        if deadline is None or deadline <= now:
            return None
        return {"cooldown_until": deadline, "remaining_seconds": deadline - now, "error": row["error"]}

    def record_compression_failure_cooldown(self, session_id, cooldown_until, error=None):
        with self._write() as conn:
            state.record_cooldown(conn, self.scope, session_id, cooldown_until, error)

    def restore_compression_failure_cooldown_row(self, session_id, snapshot):
        with self._write() as conn:
            state.restore_cooldown(conn, self.scope, session_id, snapshot)

    def clear_compression_failure_cooldown(self, session_id):
        self.restore_compression_failure_cooldown_row(session_id, {
            "session_exists": True, "cooldown_until": None, "error": None})

    def _compression_number(self, session_id, column, cast=int):
        with self._read() as conn:
            row = sessions.raw_session(conn, self.scope, session_id)
            return max(cast(0), cast(row[column] or 0)) if row else cast(0)

    def _set_compression_number(self, session_id, column, value):
        with self._write() as conn:
            if sessions.lock_session(conn, self.scope, session_id) is not None:
                sessions.update_session(conn, self.scope, session_id, {column: value})

    def get_compression_fallback_streak(self, session_id):
        return self._compression_number(session_id, "compression_fallback_streak")

    def set_compression_fallback_streak(self, session_id, streak):
        self._set_compression_number(session_id, "compression_fallback_streak", max(0, int(streak)))

    def get_compression_ineffective_count(self, session_id):
        return self._compression_number(session_id, "compression_ineffective_count")

    def set_compression_ineffective_count(self, session_id, count):
        self._set_compression_number(session_id, "compression_ineffective_count", max(0, int(count)))

    def get_compression_overload_streak(self, session_id):
        return self._compression_number(session_id, "compression_overload_streak")

    def set_compression_overload_streak(self, session_id, streak):
        self._set_compression_number(session_id, "compression_overload_streak", max(0, int(streak)))

    def increment_compression_overload_streak(self, session_id):
        with self._write() as conn:
            if sessions.lock_session(conn, self.scope, session_id) is None:
                return None
            return conn.scalar(table.update().where(sessions.where_session(self.scope, session_id))
                .values(compression_overload_streak=table.c.compression_overload_streak + 1)
                .returning(table.c.compression_overload_streak))

    def get_compression_recovery_deadline(self, session_id):
        return self._compression_number(session_id, "compression_recovery_deadline", float)

    def set_compression_recovery_deadline(self, session_id, deadline):
        try:
            normalized = max(0.0, float(deadline or 0))
        except (TypeError, ValueError):
            normalized = 0.0
        self._set_compression_number(session_id, "compression_recovery_deadline", normalized or None)

    def reopen_if_explicitly_closed(self, session_id, *, provenance, patience_s=None):
        self._assert_open()
        with self._transactions.write(lock_timeout=patience_s) as conn:
            return state.reopen(conn, self.scope, session_id)

    def reopen_orphaned_compression_session(self, session_id):
        with self._write() as conn:
            return state.reopen(conn, self.scope, session_id, orphan=True)

    def find_live_compression_child(self, parent_session_id):
        with self._read() as conn:
            rows = state.children(conn, self.scope, parent_session_id, live_only=True)
            return sessions.get_session(conn, self.scope, rows[0]["id"]) if len(rows) == 1 else None

    def finalize_orphaned_compression_sessions(self):
        with self._write() as conn:
            return state.finalize_orphans(conn, self.scope)

    def get_compression_lineage(self, session_id):
        with self._read() as conn:
            return state.lineage(conn, self.scope, session_id)
