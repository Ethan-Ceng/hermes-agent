"""Durable handoff state transitions under scoped lineage locks."""

from sqlalchemy import or_, select

from hermes_db.repositories import sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.core.values import decode_text, encode_text


class SessionHandoffs:
    def _handoff_update(self, session_id, values, *conditions):
        with self._write() as conn:
            if sessions.lock_session(conn, self.scope, session_id) is None:
                return False
            return sessions.update_session(conn, self.scope, session_id, values, *conditions) > 0

    def request_handoff(self, session_id, platform):
        return self._handoff_update(session_id, {"handoff_state": "pending", "handoff_platform": platform, "handoff_error": None},
            or_(table.c.handoff_state.is_(None), table.c.handoff_state.in_(("completed", "failed"))))

    def get_handoff_state(self, session_id):
        with self._read() as conn:
            row = sessions.raw_session(conn, self.scope, session_id)
            return {"state": row["handoff_state"], "platform": row["handoff_platform"],
                    "error": decode_text(row["handoff_error"])} if row else None

    def list_pending_handoffs(self):
        with self._read() as conn:
            ids = conn.execute(select(table.c.id).where(table.c.store_id == self.scope.require_store_id(),
                table.c.handoff_state == "pending").order_by(table.c.started_at)).scalars().all()
            rows = sessions.get_sessions(conn, self.scope, ids)
            return [rows[sid] for sid in ids]

    def claim_handoff(self, session_id):
        return self._handoff_update(session_id, {"handoff_state": "running"}, table.c.handoff_state == "pending")

    def has_pending_handoffs(self):
        with self._read() as conn:
            return conn.scalar(select(table.c.id).where(table.c.store_id == self.scope.require_store_id(),
                table.c.handoff_state == "pending").limit(1)) is not None

    def complete_handoff(self, session_id):
        self._handoff_update(session_id, {"handoff_state": "completed", "handoff_error": None})

    def fail_handoff(self, session_id, error, *, only_states=None):
        conditions = [table.c.handoff_state.in_(only_states)] if only_states else []
        return self._handoff_update(session_id, {"handoff_state": "failed", "handoff_error": encode_text(error[:500])}, *conditions)

    def reclaim_stale_running_handoffs(self, error):
        with self._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            rows = conn.execute(select(table).where(table.c.store_id == self.scope.require_store_id(),
                table.c.handoff_state == "running")).mappings().all()
            for root in sorted({row["lineage_root_id"] for row in rows}):
                sessions.lock_root(conn, self.scope, root)
            ids = [row["id"] for row in rows]
            if ids:
                conn.execute(table.update().where(table.c.store_id == self.scope.require_store_id(), table.c.id.in_(ids))
                    .values(handoff_state="failed", handoff_error=encode_text(error[:500])))
            return ids
