"""Scoped Bot/automation request lookups and roster reads."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import bot_views
from hermes_db.tables.runtime import session_admissions


class RuntimeBot:
    def request_admission_id(self, session_id, request_id):
        with self._store._read() as conn:
            return conn.scalar(select(session_admissions.c.admission_id).where(
                session_admissions.c.store_id == self.scope.require_store_id(), session_admissions.c.target_session_id == session_id,
                session_admissions.c.request_id == request_id).limit(1))

    def has_request(self, request_id, *, session_id=None):
        with self._store._read() as conn:
            query = select(session_admissions.c.admission_id).where(session_admissions.c.store_id == self.scope.require_store_id(),
                session_admissions.c.request_id == request_id)
            if session_id is not None:
                query = query.where(session_admissions.c.target_session_id == session_id)
            return conn.scalar(query.limit(1)) is not None

    def holds_admissions(self, session_ids):
        with self._store._read() as conn:
            return conn.scalar(select(session_admissions.c.admission_id).where(
                session_admissions.c.store_id == self.scope.require_store_id(),
                session_admissions.c.target_session_id.in_(session_ids)).limit(1)) is not None

    def bot_sessions(self, subject, operator):
        with self._store._read() as conn:
            return bot_views.roster(conn, self.scope, subject, operator)
