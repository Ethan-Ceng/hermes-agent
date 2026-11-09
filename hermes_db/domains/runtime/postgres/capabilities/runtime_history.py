"""Authority's scoped history read gates; claims themselves commit with mutations."""

from hermes_db.domains.runtime.postgres.queries import history_access


class RuntimeHistory:
    def authorize_history(self, actor, session_id, *, native_transport):
        with self._store._read() as conn:
            return history_access.authorize_claim(conn, self.scope, actor, session_id,
                own_profile=self._store._own_profile, native_transport=native_transport)

    def require_history_leaf(self, session_id):
        from hermes_db.domains.sessions.postgres.operations.compression_state import lineage
        with self._store._read() as conn:
            history_access.require_leaf(conn, self.scope, session_id, lineage(conn, self.scope, session_id))
