"""Explicit storage identity and read-only health/reference capabilities."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries.archive_refs import referenced_names
from hermes_db.tables.conversations import messages, sessions


class SessionHealth:
    def message_storage_state(self, message_id):
        with self._read() as conn:
            row = conn.execute(select(messages.c.session_id, messages.c.active, messages.c.compacted).where(
                messages.c.store_id == self.scope.require_store_id(), messages.c.id == message_id)).mappings().first()
            return dict(row) if row else None

    @property
    def profile_home(self):
        return self.scope.profile_home

    def storage_health(self):
        with self._read() as conn:
            conn.execute(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id()).limit(1)).first()
        return {"backend": "postgresql", "status": "ok"}

    def referenced_spillover_names(self):
        with self._read() as conn:
            return referenced_names(conn, self.scope)

    def latest_message_preview(self, session_id):
        with self._read() as conn:
            preview = conn.scalar(select(messages.c.roster_preview).where(messages.c.store_id == self.scope.require_store_id(),
                messages.c.session_id == session_id, messages.c.active == 1, messages.c.roster_preview.is_not(None))
                .order_by(messages.c.id.desc()).limit(1))
        return bytes(preview).decode("utf-8") if preview is not None else ""
