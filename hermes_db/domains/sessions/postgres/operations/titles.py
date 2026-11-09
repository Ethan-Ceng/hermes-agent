"""Title authority, conflict transfer, and canonical Bot Chat protection."""

from sqlalchemy import case, func, select

from hermes_db.domains.sessions.postgres.queries import sessions as repo
from hermes_db.tables.conversations import messages, sessions
from hermes_db.core.values import decode_text, encode_text

RANK = {"derived": 0, "llm": 1, "user": 2}
BOT_TITLE = "Bot Chat"


def retire_bot_chat(conn, scope, ids):
    from hermes_db.domains.sessions.rules import _RECOVERABLE_END_REASONS
    held = list(conn.execute(select(sessions.c.id).where(sessions.c.store_id == scope.require_store_id(),
        sessions.c.id.in_(ids), sessions.c.title == encode_text(BOT_TITLE))).scalars())
    if not held:
        return
    conn.execute(sessions.update().where(sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(ids)).values(
        hidden=0, end_reason=case((sessions.c.end_reason.in_(_RECOVERABLE_END_REASONS), None), else_=sessions.c.end_reason)))
    conn.execute(sessions.update().where(sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(held)).values(
        title=None, title_search=None, title_source=None))


def set_title(transactions, scope, session_id, title, source):
    with transactions.write() as conn:
        return bool(set_title_on_connection(conn, scope, session_id, title, source))


def set_title_on_connection(conn, scope, session_id, title, source):
    from hermes_db.domains.sessions.rules import sanitize_title

    title = sanitize_title(title)
    repo.lock_store(conn, scope, exclusive=True)
    row = repo.lock_session(conn, scope, session_id)
    if row is None:
        return set()
    current = decode_text(row["title"])
    if current == BOT_TITLE and row["hidden"] and title != BOT_TITLE:
        if source == "user":
            raise ValueError("The canonical Bot Chat cannot be renamed")
        return set()
    if source != "user" and current is not None and RANK.get(row["title_source"], 2 if row["title_source"] is None else 0) >= RANK[source]:
        return set()
    conflict = _free_title(conn, scope, row, title) if title else None
    repo.update_session(conn, scope, session_id, {"title": encode_text(title), "title_search": title,
                                                  "title_source": source if title else None})
    return {session_id, *([conflict] if conflict else [])}


def _free_title(conn, scope, target, title):
    conflict = conn.execute(select(sessions).where(sessions.c.store_id == scope.require_store_id(),
        sessions.c.title == encode_text(title), sessions.c.id != target["id"])).mappings().one_or_none()
    if conflict is None:
        return
    ancestor = _is_ancestor(conn, scope, conflict["id"], target)
    retired_bot = title == BOT_TITLE and conflict["archived"] and conflict["hidden"]
    ghost = (not conflict["message_count"] and conflict["ended_at"] is not None and not conflict["archived"]
             and not conn.scalar(select(func.count()).select_from(messages).where(
                 messages.c.store_id == scope.require_store_id(), messages.c.session_id == conflict["id"])))
    if ancestor or retired_bot or (ghost and not conflict["hidden"]):
        values = {"title": None, "title_search": None}
        if not ancestor:
            values["title_source"] = None
        repo.update_session(conn, scope, conflict["id"], values)
        return conflict["id"]
    raise ValueError("Title is already in use by another session")


def _is_ancestor(conn, scope, ancestor_id, target):
    parents = {row["id"]: row["parent_session_id"] for row in repo.lineage_rows(conn, scope, target["id"])}
    current, seen = target["parent_session_id"], set()
    while current and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = parents.get(current)
    return False
