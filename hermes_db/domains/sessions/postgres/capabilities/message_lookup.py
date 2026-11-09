"""Bounded message probes and transcript navigation."""

from sqlalchemy import func, select

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.backends.postgresql.expressions.projections import display_value, query_token
from hermes_db.tables.conversations import messages, sessions
from hermes_db.tables.gateway import conversation_generations
from hermes_db.core.values import explicit_fork


class SessionMessageLookup:
    def latest_message_row_id(self, session_id, *, role="user", offset=0, require_text=True):
        if not session_id or role not in {"user", "assistant"} or offset < 0:
            return None
        with self._read() as conn:
            filters = [repo.where(self.scope, [session_id]), messages.c.active == 1, messages.c.role == role]
            if require_text:
                filters.append(func.trim(messages.c.search_content) != "")
            return conn.scalar(select(messages.c.id).where(*filters).order_by(messages.c.id.desc()).limit(1).offset(int(offset)))

    def latest_conversation_role(self, session_id):
        with self._read() as conn:
            return conn.scalar(select(messages.c.role).where(repo.where(self.scope, [session_id]), messages.c.active == 1,
                messages.c.role.not_in(("session_meta", "system"))).order_by(messages.c.id.desc()).limit(1))

    def get_message_role(self, session_id, row_id):
        with self._read() as conn:
            return conn.scalar(select(messages.c.role).where(repo.where(self.scope, [session_id]),
                messages.c.id == int(row_id), messages.c.active == 1))

    def get_messages_around(self, session_id, around_message_id, window=5):
        with self._read() as conn:
            return around(conn, self.scope, session_id, around_message_id, window)

    def has_platform_message_id(self, session_id, platform_message_id):
        with self._read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self.scope, [session_id]),
                messages.c.platform_message_id == platform_message_id).limit(1)) is not None

    def has_gateway_input_owner(self, session_id, owner):
        with self._read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self.scope, [session_id]), messages.c.role == "user",
                messages.c.observed == 0, repo.visible(), display_value(messages.c.display_metadata, "gateway_input_owner") == query_token(owner))
                .limit(1)) is not None

    def latest_conversation_boundary(self, session_key, source):
        if not session_key or not source:
            return None
        table = conversation_generations
        with self._read() as conn:
            generation = conn.scalar(select(table.c.generation).where(table.c.store_id == self.scope.require_store_id(),
                table.c.session_key == session_key, table.c.source == source))
        return generation if generation and generation > 0 else None

    def find_pr_url_messages(self, session_ids):
        with self._read() as conn:
            rows = repo.select_rows(conn, self.scope, [sid for sid in session_ids if sid],
                messages.c.role == "tool", messages.c.search_content.contains("/pull/", autoescape=True))
        return [{"session_id": row["session_id"], "content": row["content"]} for row in rows]

    def display_message_count(self, session_id):
        from hermes_db.domains.sessions.postgres.capabilities.message_reads import display_ids
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(display_ids(conn, self.scope, session_id).subquery()))

    def resolve_resume_session_id(self, session_id):
        if not session_id:
            return session_id
        with self._read() as conn:
            initial = session_repo.compression_tip(conn, self.scope, session_id) or session_id
            current, best, seen = initial, None, set()
            for _ in range(32):
                if current in seen:
                    break
                seen.add(current)
                if conn.scalar(select(messages.c.id).where(repo.where(self.scope, [current])).limit(1)) is not None:
                    best = current
                children = conn.execute(select(sessions).where(sessions.c.store_id == self.scope.require_store_id(),
                    sessions.c.parent_session_id == current).order_by(sessions.c.started_at.desc(), sessions.c.id.desc())).mappings()
                child = next((row for row in children if row["source"] != "tool" and not explicit_fork(row)), None)
                if child is None:
                    break
                current = child["id"]
            return best or initial


def around(conn, scope, session_id, anchor_id, window):
    window = max(0, window)
    if repo.one(conn, scope, session_id, anchor_id) is None:
        return {"window": [], "messages_before": 0, "messages_after": 0}
    before = repo.select_rows(conn, scope, [session_id], messages.c.id <= anchor_id, limit=window + 1, latest=True)
    after = repo.select_rows(conn, scope, [session_id], messages.c.id > anchor_id, limit=window)
    return {"window": [codec._row_to_message_dict(row, warn_context="get_messages_around", summary_flag=False)
        for row in [*before, *after]], "messages_before": len(before) - 1, "messages_after": len(after)}
