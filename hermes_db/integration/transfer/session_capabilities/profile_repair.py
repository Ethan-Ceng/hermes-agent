"""Profile repair capabilities over current PG rows; no legacy file readers."""

from sqlalchemy import func, select

from hermes_db.integration.postgres.operations import profile_repair
from hermes_db.domains.sessions.postgres.queries import gateway
from hermes_db.integration.postgres.queries import profile_repair as repo
from hermes_db.tables.conversations import messages, sessions
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings
from hermes_state_profile_repair import session_key_profile


class SessionProfileRepair:
    def find_crossed_profile_sessions(self, owner):
        with self._read() as conn:
            return repo.crossed(conn, self.scope, owner)

    def _ledgered_session_ids(self):
        with self._read() as conn:
            return repo.ledgered_ids(conn, self.scope)

    def list_gateway_routing_rows(self):
        with self._read() as conn:
            return [{key: value for key, value in row.items() if key != "store_id"}
                for row in sorted(gateway.routing_rows(conn, self.scope), key=lambda row: (row["scope"], row["session_key"]))]

    def find_profile_less_telegram_topic_rows(self):
        with self._read() as conn:
            rows = conn.execute(select(bindings.c.chat_id, bindings.c.thread_id, bindings.c.session_key).where(
                bindings.c.store_id == self.scope.require_store_id(), bindings.c.profile_name == "default")
                .order_by(bindings.c.chat_id, bindings.c.thread_id)).mappings()
            return [{**row, "key_profile": target} for row in rows
                if (target := session_key_profile(row["session_key"])) not in (None, "default")]

    def count_messages_all(self, session_id):
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(messages).where(
                messages.c.store_id == self.scope.require_store_id(), messages.c.session_id == session_id))

    def relabel_sessions_to_key_profile(self, ids):
        with self._write() as conn:
            return profile_repair.repair_sessions(conn, self.scope, ids)

    def sever_crossed_parents(self, ids):
        with self._write() as conn:
            return profile_repair.repair_sessions(conn, self.scope, ids, sever=True)

    def rekey_legacy_main_sessions(self, ids, profile):
        with self._write() as conn:
            return profile_repair.repair_sessions(conn, self.scope, ids, rekey=profile)

    def delete_gateway_routing_rows(self, rows):
        with self._write() as conn:
            return profile_repair.delete_routes(conn, self.scope, rows)

    def insert_gateway_routing_rows_if_absent(self, rows):
        with self._write() as conn:
            return profile_repair.insert_routes(conn, self.scope, rows)

    def relabel_telegram_topic_rows(self, rows):
        with self._write() as conn:
            return profile_repair.repair_topics(conn, self.scope, rows)

    def key_profiles_for_chat(self, platform, chat_id):
        with self._read() as conn:
            keys = conn.execute(select(sessions.c.session_key).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.source == platform, sessions.c.chat_id == str(chat_id))).scalars()
            return {profile for key in keys if (profile := session_key_profile(key)) is not None}
