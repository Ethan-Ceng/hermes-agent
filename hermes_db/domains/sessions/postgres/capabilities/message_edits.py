"""Row-addressed sidecar and visibility edits, serialized with transcript writes."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.tables.conversations import messages


def valid_row_id(row_id):
    return isinstance(row_id, int) and not isinstance(row_id, bool) and row_id > 0


class SessionMessageEdits:
    def set_message_api_content(self, session_id, row_id, content, api_content):
        from hermes_state_messages import _scrub_surrogates
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            return self._backfill_api_content(conn, session_id, row_id, content, _scrub_surrogates(api_content))

    def _backfill_api_content(self, conn, session_id, row_id, content, api_content):
        from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
        row = repo.one(conn, self.scope, session_id, row_id)
        if not row or row["role"] != "user" or not row["active"] or content_to_bytes(row["content"]) != content_to_bytes(codec._encode_content(content)):
            return 0
        return repo.update_row(conn, self.scope, session_id, row_id, {"api_content": api_content})

    def set_latest_user_api_content(self, session_id, content, api_content):
        from hermes_state_messages import _scrub_surrogates
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            row_id = conn.scalar(select(messages.c.id).where(repo.where(self.scope, [session_id]),
                messages.c.active == 1, messages.c.role == "user").order_by(messages.c.id.desc()).limit(1))
            return self._backfill_api_content(conn, session_id, row_id, content, _scrub_surrogates(api_content)) if row_id else 0

    def set_user_message_content(self, session_id, row_id, content, display_metadata=None):
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            row = repo.one(conn, self.scope, session_id, row_id)
            if not row or not row["active"] or row["role"] != "user":
                return 0
            values = {"content": codec._encode_content(content)}
            if display_metadata is not None:
                from hermes_db.domains.sessions.postgres.support.message_codec import merge_display_metadata
                current = codec._decode_display_metadata(row["display_metadata"])
                patch = codec._decode_display_metadata(codec._encode_display_metadata(display_metadata)) or {}
                merged = merge_display_metadata(current, patch)
                values.update(api_content=None, display_metadata=codec._encode_display_metadata(merged))
            return repo.update_row(conn, self.scope, session_id, row_id, values)

    def deactivate_message(self, session_id, row_id):
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            return repo.update_row(conn, self.scope, session_id, row_id, {"active": 0})

    def deactivate_messages_by_display_kind(self, session_id, display_kind):
        if not session_id or not display_kind:
            return 0
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            result = conn.execute(messages.update().where(repo.where(self.scope, [session_id]), messages.c.active == 1,
                messages.c.display_kind == display_kind).values(active=0))
            if result.rowcount:
                repo.bump_revision(conn, self.scope, session_id)
            return result.rowcount

    def resolve_active_row_id(self, session_id, row_id):
        if not session_id or not valid_row_id(row_id):
            return None
        with self._read() as conn:
            row = repo.one(conn, self.scope, session_id, row_id)
            if not row:
                return None
            if row["active"]:
                return row_id
            from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
            clones = list(conn.execute(select(messages.c.id).where(repo.where(self.scope, [session_id]),
                messages.c.active == 1, messages.c.id > row_id, messages.c.role == row["role"],
                messages.c.content.is_not_distinct_from(content_to_bytes(row["content"])),
                messages.c.timestamp == row["timestamp"]).limit(2)).scalars())
            return clones[0] if len(clones) == 1 else None

    def clear_messages(self, session_id):
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            conn.execute(messages.delete().where(repo.where(self.scope, [session_id])))
            session_repo.update_session(conn, self.scope, session_id, {"message_count": 0, "tool_call_count": 0})
            repo.bump_revision(conn, self.scope, session_id)

    def set_latest_matching_message_display_kind(self, session_id, *, role, content, display_kind, display_metadata=None):
        if not session_id or not content or not display_kind:
            return False
        from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
        from hermes_state_messages import _scrub_surrogates
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            row_id = conn.scalar(select(messages.c.id).where(repo.where(self.scope, [session_id]), messages.c.role == role,
                messages.c.content == content_to_bytes(codec._encode_content(content)), messages.c.active == 1)
                .order_by(messages.c.id.desc()).limit(1))
            if row_id is None:
                return False
            repo.update_row(conn, self.scope, session_id, row_id, {"display_kind": _scrub_surrogates(display_kind),
                "display_metadata": codec._encode_display_metadata(display_metadata)})
            return True
