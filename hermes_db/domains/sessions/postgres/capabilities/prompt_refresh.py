"""Durable refresh epochs defer prompt rebuilds to the owning session's next turn."""

from sqlalchemy import BigInteger, cast, func, or_, select

from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import state_meta
from hermes_state_prompt_refresh import PROFILE_KEY, SESSION_KEY_PREFIX


class SessionPromptRefresh:
    def request_prompt_refresh(self, session_id=None):
        key = PROFILE_KEY if session_id is None else SESSION_KEY_PREFIX + session_id
        with self._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            epoch = 1 + (conn.scalar(select(func.max(cast(state_meta.c.value, BigInteger))).where(
                state_meta.c.store_id == self.scope.require_store_id(), or_(state_meta.c.key == PROFILE_KEY,
                state_meta.c.key.startswith(SESSION_KEY_PREFIX, autoescape=True)))) or 0)
            runtime.set_meta(conn, self.scope, key, str(epoch))
        return epoch

    def prompt_refresh_epoch(self, session_id):
        with self._read() as conn:
            return conn.scalar(select(func.max(cast(state_meta.c.value, BigInteger))).where(
                state_meta.c.store_id == self.scope.require_store_id(), state_meta.c.key.in_((PROFILE_KEY, SESSION_KEY_PREFIX + session_id)))) or 0

    def count_sessions_with_stored_prompt(self):
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(table).where(table.c.store_id == self.scope.require_store_id(),
                or_(table.c.system_prompt_hash.is_not(None), table.c.system_prompt.is_not(None))))
