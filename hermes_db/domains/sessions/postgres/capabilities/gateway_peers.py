"""Gateway peer queries and identity updates for one owning store."""

from hermes_db.domains.sessions.postgres.operations import gateway_peers as operations
from hermes_db.domains.sessions.postgres.queries import gateway_peers as repo, sessions


class SessionGatewayPeers:
    _ORPHAN_ADOPTION_MAX_GAP_S = 900.0

    def record_gateway_session_peer(self, session_id, *, source, user_id=None, session_key=None, chat_id=None,
        chat_type=None, thread_id=None, display_name=None, origin_json=None, include_compression_ancestors=False, transport_profile=None):
        with self._write() as conn:
            if session_id and session_key:
                operations.record(conn, self.scope, session_id, source=source, own_profile=self._own_profile,
                    include_compression_ancestors=include_compression_ancestors, user_id=user_id, session_key=session_key,
                    chat_id=chat_id, chat_type=chat_type, thread_id=thread_id, display_name=display_name,
                    origin_json=origin_json, transport_profile=transport_profile)

    def list_gateway_sessions(self, *, platform=None, active_only=True):
        self.flush_for_read()
        with self._read() as conn:
            ids = repo.newest_ids(conn, self.scope, platform=platform, active_only=active_only)
            rows = sessions.get_sessions(conn, self.scope, ids)
            from hermes_db.domains.sessions.postgres.queries.session_queries import last_activity
            from hermes_db.tables.conversations import sessions as table
            from sqlalchemy import select
            activity = dict(conn.execute(select(table.c.id, last_activity(conn)).where(table.c.store_id == self.scope.require_store_id(),
                table.c.id.in_(ids))).all())
            return [dict(rows[sid], last_active=activity[sid]) for sid in ids]

    def find_latest_gateway_session_for_peer(self, *, source, user_id=None, session_key=None, chat_id=None, chat_type=None, thread_id=None):
        with self._read() as conn:
            if not session_key:
                return None
            return repo.peer_candidate(conn, self.scope, source=source, session_key=session_key, owner=self._own_profile,
                user_id=user_id, chat_id=chat_id, chat_type=chat_type, thread_id=thread_id)

    def list_never_active_keyed_sessions(self, *, older_than_days):
        with self._read() as conn:
            return repo.never_active(conn, self.scope, older_than_days)

    def find_orphaned_gateway_sessions(self, *, max_gap_s=None):
        gap = self._ORPHAN_ADOPTION_MAX_GAP_S if max_gap_s is None else float(max_gap_s)
        with self._read() as conn:
            return repo.orphans(conn, self.scope, owner=self._own_profile, max_gap_s=gap)

    def adopt_orphaned_gateway_session(self, orphan_id, donor_id):
        with self._write() as conn:
            return operations.adopt(conn, self.scope, orphan_id, donor_id, owner=self._own_profile)
