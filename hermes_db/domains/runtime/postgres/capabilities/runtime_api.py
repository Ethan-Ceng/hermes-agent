"""Current server-owned API binding capability."""

from hermes_db.domains.runtime.postgres.operations import api_binding


class RuntimeApi:
    def create_api_session(self, *, session_id, source, title, **values):
        from hermes_db.domains.sessions.postgres.operations import sessions as lifecycle, titles
        from hermes_db.domains.sessions.postgres.queries import sessions
        try:
            with self._write() as conn:
                sessions.lock_store(conn, self.scope, exclusive=True)
                if sessions.raw_session(conn, self.scope, session_id) is not None:
                    return None, ("session_exists", "Session already exists")
                if sessions.retired_session(conn, self.scope, session_id):
                    return None, ("session_deleted", "Session was deleted; its id cannot be reused")
                lifecycle.create_on_connection(conn, self.scope, session_id, source,
                    own_profile=self._store._own_profile, **values)
                if title is not None:
                    titles.set_title_on_connection(conn, self.scope, session_id, str(title), "user")
                    sessions.update_session(conn, self.scope, session_id, {"title_source": None})
                return sessions.get_session(conn, self.scope, session_id), None
        except ValueError as exc:
            return None, f"title:{exc}"

    def queued_api_sessions(self):
        from sqlalchemy import select
        from hermes_db.tables.runtime import session_admissions as table
        with self._store._read() as conn:
            return list(conn.scalars(select(table.c.target_session_id).where(
                table.c.store_id == self.scope.require_store_id(), table.c.principal_id == "api",
                table.c.status == "queued").distinct()))

    def bind_api_session(self, **kwargs):
        with self._write() as conn:
            return api_binding.bind(conn, self.scope, own_profile=self._store._own_profile, **kwargs)
