"""Scoped scheduler metadata and durable worker provenance."""

from sqlalchemy import or_, select

from hermes_db.domains.sessions.postgres.queries import messages
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.conversations import sessions
from hermes_db.tables.runtime import state_meta


class SessionBookkeeping:
    def get_meta(self, key):
        with self._read() as conn:
            return runtime.meta(conn, self.scope, key)

    def set_meta(self, key, value, *, cursor=None):
        if cursor is not None:
            runtime.set_meta(cursor, self.scope, key, value)
        else:
            with self._write() as conn:
                runtime.set_meta(conn, self.scope, key, value)

    def list_meta_prefix(self, prefix):
        if not prefix:
            return []
        with self._read() as conn:
            return [tuple(row) for row in conn.execute(select(state_meta.c.key, state_meta.c.value).where(
                state_meta.c.store_id == self.scope.require_store_id(), state_meta.c.key.startswith(prefix, autoescape=True)))]

    def is_kanban_owned_session(self, session_id):
        with self._read() as conn:
            ids = messages.resume_lineage(conn, self.scope, session_id)
            return conn.scalar(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.id.in_(ids), or_(sessions.c.source == "kanban", sessions.c.created_source == "kanban")).limit(1)) is not None
