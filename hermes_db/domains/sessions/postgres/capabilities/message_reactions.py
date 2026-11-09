"""Reactions are separate metadata; announcements never rewrite model history."""

import time

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.backends.postgresql.expressions.projections import display_value
from hermes_db.tables.conversations import messages


def _reaction_list(metadata):
    value = (metadata or {}).get("reactions")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _reaction_row(conn, scope, session_id, row_id):
    ids = repo.resume_lineage(conn, scope, session_id)
    rows = repo.select_rows(conn, scope, ids, messages.c.id == row_id, repo.visible(), limit=1)
    return rows[0] if rows else None


class SessionMessageReactions:
    def set_message_reaction(self, session_id, message_row_id, emoji, *, author="user"):
        if not session_id or message_row_id is None:
            return None
        from hermes_state_messages import _scrub_surrogates
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            row = _reaction_row(conn, self.scope, session_id, message_row_id)
            if row is None:
                return None
            metadata = codec._decode_display_metadata(row["display_metadata"]) or {}
            existing = _reaction_list(metadata)
            reactions = [item for item in existing if item.get("author") != author]
            previous = next((item for item in existing if item.get("author") == author), None)
            if emoji and (previous is None or previous.get("emoji") != emoji):
                reactions.append({"emoji": _scrub_surrogates(emoji), "author": author, "at": time.time()})
            if reactions:
                metadata["reactions"] = reactions
            else:
                metadata.pop("reactions", None)
            repo.update_row(conn, self.scope, row["session_id"], message_row_id,
                            {"display_metadata": codec._encode_display_metadata(metadata)})
            return reactions

    def get_message_reactions(self, session_id, message_row_id):
        if not session_id or message_row_id is None:
            return []
        with self._read() as conn:
            row = _reaction_row(conn, self.scope, session_id, message_row_id)
            return _reaction_list(codec._decode_display_metadata(row["display_metadata"])) if row else []

    def take_unseen_reactions(self, session_id, *, author="user"):
        if not session_id:
            return []
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            ids = repo.resume_lineage(conn, self.scope, session_id)
            rows = repo.select_rows(conn, self.scope, ids, repo.visible(),
                                    display_value(messages.c.display_metadata, "reactions").is_not(None))
            pending = []
            for row in rows:
                metadata = codec._decode_display_metadata(row["display_metadata"]) or {}
                changed = False
                for reaction in _reaction_list(metadata):
                    if reaction.get("author") != author or reaction.get("seen"):
                        continue
                    reaction["seen"] = True
                    changed = True
                    content = codec._decode_content(row["content"])
                    pending.append({"row_id": row["id"], "role": row["role"], "emoji": reaction.get("emoji") or "",
                                    "text": content if isinstance(content, str) else ""})
                if changed:
                    repo.update_row(conn, self.scope, row["session_id"], row["id"],
                                    {"display_metadata": codec._encode_display_metadata(metadata)})
            return pending
