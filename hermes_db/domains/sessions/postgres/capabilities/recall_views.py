"""Bounded recall windows/bookends and human turn navigation over current messages."""

from sqlalchemy import func, or_

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo
from hermes_db.domains.sessions.postgres.capabilities.message_lookup import around
from hermes_db.tables.conversations import messages


def _bookends(conn, scope, sid, rows, bookend, keep_roles):
    if bookend <= 0:
        return [], []
    conditions = [func.length(messages.c.content) > 1, func.substr(messages.c.content, 1, 2) != b"T\x00"]
    if keep_roles is not None:
        conditions.append(messages.c.role.in_(keep_roles))
    start = repo.select_rows(conn, scope, [sid], *conditions, messages.c.id < rows[0]["id"], limit=bookend)
    end = repo.select_rows(conn, scope, [sid], *conditions, messages.c.id > rows[-1]["id"], limit=bookend, latest=True)
    return tuple([codec._row_to_message_dict(row, warn_context="get_anchored_view", summary_flag=False) for row in part]
        for part in (start, end))


class SessionRecallViews:
    def get_anchored_view(self, session_id, around_message_id, window=5, bookend=3, keep_roles=("user", "assistant")):
        with self._read() as conn:
            result = around(conn, self.scope, session_id, around_message_id, window)
            rows = result["window"]
            start, end = _bookends(conn, self.scope, session_id, rows, max(0, bookend), keep_roles) if rows else ([], [])
        if keep_roles is not None:
            result["window"] = [row for row in rows if row["id"] == around_message_id or row["role"] in keep_roles]
        return {**result, "bookend_start": start, "bookend_end": end}

    def list_recent_user_messages(self, session_id, limit=20, include_inactive=False):
        from agent.context_compressor import ContextCompressor
        from agent.skill_commands import describe_skill_invocation
        from hermes_state_search import _flatten_text
        conditions = [messages.c.role == "user", or_(messages.c.display_kind.is_(None), messages.c.display_kind.in_(("", "steer")))]
        if not include_inactive:
            conditions.append(messages.c.active == 1)
        with self._read() as conn:
            rows = repo.select_rows(conn, self.scope, [session_id], *conditions, limit=max(0, int(limit) * 2 + 5), latest=True)
        result = []
        for row in reversed(rows):
            if len(result) >= int(limit):
                break
            decoded = codec._decode_content(row["content"])
            if ContextCompressor._is_context_summary_content(decoded):
                continue
            preview = describe_skill_invocation(decoded) or decoded if isinstance(decoded, str) else _flatten_text(decoded)
            preview = " ".join(preview.split())
            result.append({"id": row["id"], "timestamp": row["timestamp"], "preview": preview[:77] + "..." if len(preview) > 80 else preview})
        return result
