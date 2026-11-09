"""Title-facing methods kept out of the session facade."""

import re

from sqlalchemy import select

from hermes_db.operations import titles
from hermes_db.repositories import sessions as repo
from hermes_db.tables.conversations import sessions
from hermes_db.core.values import decode_text, encode_text


class SessionTitles:
    MAX_TITLE_LENGTH = 100
    TITLE_SOURCE_DERIVED, TITLE_SOURCE_LLM, TITLE_SOURCE_USER = "derived", "llm", "user"
    CANONICAL_BOT_CHAT_TITLE = titles.BOT_TITLE

    @staticmethod
    def sanitize_title(value):
        from hermes_state_titles import SessionTitlesMixin
        return SessionTitlesMixin.sanitize_title(value)

    def set_session_title(self, session_id, title):
        self._assert_open()
        return titles.set_title(self._transactions, self.scope, session_id, title, "user")

    def set_auto_title(self, session_id, title, *, source):
        self._assert_open()
        if source not in ("derived", "llm"):
            raise ValueError("Invalid automatic title source")
        return titles.set_title(self._transactions, self.scope, session_id, title, source)

    def displace_bot_chat(self, session_id, title):
        with self._write() as conn:
            repo.lock_store(conn, self.scope, exclusive=True)
            repo.lock_session(conn, self.scope, session_id)
            return repo.update_session(conn, self.scope, session_id,
                {"title": encode_text(title), "title_search": title, "title_source": "user", "hidden": 0},
                sessions.c.title == encode_text("Bot Chat")) > 0

    def get_session_title(self, session_id):
        row = self.get_session(session_id)
        return row["title"] if row else None

    def get_session_title_source(self, session_id):
        row = self.get_session(session_id)
        return row["title_source"] if row and row["title"] is not None else None

    def set_session_title_source(self, session_id, source):
        if source not in titles.RANK:
            raise ValueError("Invalid title source")
        with self._write() as conn:
            repo.lock_session(conn, self.scope, session_id)
            return repo.update_session(conn, self.scope, session_id, {"title_source": source}, sessions.c.title.is_not(None)) > 0

    def get_session_by_title(self, title):
        with self._read() as conn:
            session_id = conn.scalar(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                                                                sessions.c.title == encode_text(title)))
            row = repo.get_session(conn, self.scope, session_id) if session_id else None
            if row and title == titles.BOT_TITLE and row['archived']:
                from hermes_state_titles import bot_chat_title_released
                tip = repo.raw_session(conn, self.scope, repo.compression_tip(conn, self.scope, row['id'])) or row
                if bot_chat_title_released(row['archived'], row['auto_archived'], tip['end_reason']):
                    return None
            return row

    def resolve_session_by_title(self, title):
        exact = self.get_session_by_title(title)
        if title == titles.BOT_TITLE:
            return exact['id'] if exact else None
        with self._read() as conn:
            latest = conn.scalar(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.title_search.startswith(title + " #", autoescape=True))
                .order_by(sessions.c.started_at.desc(), sessions.c.id.desc()).limit(1))
        return latest or (exact["id"] if exact else None)

    def get_next_title_in_lineage(self, base_title):
        base = re.sub(r" #\d+$", "", base_title)
        with self._read() as conn:
            rows = conn.execute(select(sessions.c.title).where(sessions.c.store_id == self.scope.require_store_id(),
                (sessions.c.title == encode_text(base)) | sessions.c.title_search.startswith(base + " #", autoescape=True))).scalars()
            values = [decode_text(value) for value in rows]
        if not values:
            return base
        numbers = [int(value.rsplit(" #", 1)[1]) for value in values if re.fullmatch(re.escape(base) + r" #\d+", value)]
        return f"{base} #{max([1, *numbers]) + 1}"
