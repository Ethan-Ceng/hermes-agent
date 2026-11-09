"""Telegram topic state uses the same selected backend and immutable store."""

import time

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.sessions.postgres.queries import sessions as repo
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings, telegram_dm_topic_mode as modes


def _profile(value):
    return str(value or "").strip() or "default"


def _where(table, scope, **values):
    return (table.c.store_id == scope.require_store_id(), *(table.c[name] == value for name, value in values.items()))


def _row(value):
    return {key: field for key, field in value.items() if key != "store_id"} if value else None


class SessionTopics:
    def apply_telegram_topic_migration(self):
        """Alembic installs the PG tables up front; this does not activate topic mode."""
        self._assert_open()

    def enable_telegram_topic_mode(self, *, chat_id, user_id, profile_name="default", has_topics_enabled=None,
                                   allows_users_to_create_topics=None):
        now = time.time()
        values = dict(store_id=self.scope.require_store_id(), profile_name=_profile(profile_name), chat_id=str(chat_id),
            user_id=str(user_id), enabled=1, activated_at=now, updated_at=now, capability_checked_at=now,
            has_topics_enabled=None if has_topics_enabled is None else int(bool(has_topics_enabled)),
            allows_users_to_create_topics=None if allows_users_to_create_topics is None else int(bool(allows_users_to_create_topics)))
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            statement = insert(modes).values(**values)
            updates = {key: value for key, value in values.items() if key not in ("store_id", "profile_name", "chat_id", "activated_at")}
            conn.execute(statement.on_conflict_do_update(index_elements=list(modes.primary_key.columns), set_=updates))

    def disable_telegram_topic_mode(self, *, chat_id, profile_name="default", clear_bindings=True):
        values = {"profile_name": _profile(profile_name), "chat_id": str(chat_id)}
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            conn.execute(update(modes).where(*_where(modes, self.scope, **values)).values(enabled=0, updated_at=time.time()))
            if clear_bindings:
                conn.execute(delete(bindings).where(*_where(bindings, self.scope, **values)))

    def is_telegram_topic_mode_enabled(self, *, chat_id, user_id, profile_name="default"):
        with self._read() as conn:
            return bool(conn.scalar(select(modes.c.enabled).where(*_where(modes, self.scope,
                profile_name=_profile(profile_name), chat_id=str(chat_id), user_id=str(user_id)))))

    def get_telegram_topic_binding(self, *, chat_id, thread_id, profile_name="default"):
        with self._read() as conn:
            return _row(conn.execute(select(bindings).where(*_where(bindings, self.scope,
                profile_name=_profile(profile_name), chat_id=str(chat_id), thread_id=str(thread_id)))).mappings().one_or_none())

    def list_telegram_topic_bindings_for_chat(self, *, chat_id, profile_name="default"):
        with self._read() as conn:
            return [_row(row) for row in conn.execute(select(bindings).where(*_where(bindings, self.scope,
                profile_name=_profile(profile_name), chat_id=str(chat_id))).order_by(bindings.c.updated_at.desc())).mappings()]

    def get_telegram_topic_binding_by_session(self, *, session_id):
        with self._read() as conn:
            return _row(conn.execute(select(bindings).where(*_where(bindings, self.scope, session_id=str(session_id))))
                        .mappings().one_or_none())

    def is_telegram_session_linked_to_topic(self, *, session_id):
        return self.get_telegram_topic_binding_by_session(session_id=session_id) is not None

    def bind_telegram_topic(self, *, chat_id, thread_id, user_id, session_key, session_id, managed_mode="auto", profile_name="default",
                            expected_session_id=None):
        profile_name, chat_id, thread_id = _profile(profile_name), str(chat_id), str(thread_id)
        now = time.time()
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            if expected_session_id is not None:
                current = conn.scalar(select(bindings.c.session_id).where(*_where(bindings, self.scope,
                    profile_name=profile_name, chat_id=chat_id, thread_id=thread_id)))
                if current is None or current != str(expected_session_id):
                    return False
            existing = conn.execute(select(bindings).where(*_where(bindings, self.scope, session_id=str(session_id)))).mappings().one_or_none()
            if existing and (existing["profile_name"], existing["chat_id"], existing["thread_id"]) != (profile_name, chat_id, thread_id):
                raise ValueError("session is already linked to another Telegram topic")
            values = dict(store_id=self.scope.require_store_id(), profile_name=profile_name, chat_id=chat_id,
                thread_id=thread_id, user_id=str(user_id), session_key=str(session_key), session_id=str(session_id),
                managed_mode=managed_mode, linked_at=now, updated_at=now)
            statement = insert(bindings).values(**values)
            changed = {key: value for key, value in values.items() if key not in ("store_id", "profile_name", "chat_id", "thread_id", "linked_at")}
            conn.execute(statement.on_conflict_do_update(index_elements=list(bindings.primary_key.columns), set_=changed))
            return True

    def delete_telegram_topic_binding(self, *, chat_id, thread_id, profile_name="default"):
        values = {"profile_name": _profile(profile_name), "chat_id": str(chat_id)}
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            deleted = conn.execute(delete(bindings).where(*_where(bindings, self.scope, **values, thread_id=str(thread_id)))).rowcount
            if deleted and not conn.scalar(select(func.count()).select_from(bindings).where(*_where(bindings, self.scope, **values))):
                conn.execute(update(modes).where(*_where(modes, self.scope, **values)).values(enabled=0, updated_at=time.time()))
            return deleted

    def list_unlinked_telegram_sessions_for_user(self, *, chat_id, user_id, profile_name="default", limit=10):
        from sqlalchemy import exists
        from hermes_db.domains.sessions.postgres.queries import session_queries as queries
        from hermes_db.tables.conversations import sessions

        with self._read() as conn:
            statement = select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.source == "telegram", sessions.c.user_id == str(user_id),
                func.coalesce(func.nullif(func.trim(sessions.c.profile_name), ""), "default") == _profile(profile_name),
                ~exists(select(1).where(bindings.c.store_id == sessions.c.store_id, bindings.c.session_id == sessions.c.id)))
            ids = list(conn.execute(statement.order_by(queries.last_activity(conn).desc(), sessions.c.started_at.desc())
                                   .limit(None if limit < 0 else limit)).scalars())
            return queries.hydrate(conn, self.scope, ids)
