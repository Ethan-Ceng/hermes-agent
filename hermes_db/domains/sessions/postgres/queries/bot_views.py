"""Narrow Bot roster projections from the owning session scope."""

from sqlalchemy import exists, func, select

from hermes_db.domains.sessions.postgres.support.message_codec import content_from_bytes
from hermes_db.domains.sessions.postgres.operations.compression_state import lineage
from hermes_db.tables.conversations import messages, sessions
from hermes_db.core.values import decode_text, encode_text

_FIELDS = ("id", "source", "title", "started_at", "last_activity_at", "message_count", "user_id", "archived")


def roster(conn, scope, subject, operator):
    from gateway.owner_identity import same_owner
    from hermes_state_sessions import INTERNAL_LISTING_SOURCES
    owned = sessions.c.store_id == scope.require_store_id()
    from hermes_db.tables.runtime import state_meta
    from hermes_state_local import POLICY_PREFIX
    local = exists(select(state_meta.c.key).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key == POLICY_PREFIX + sessions.c.chat_id))
    columns = [sessions.c[name] for name in _FIELDS]
    canonical = conn.execute(select(*columns).where(owned, local, sessions.c.title == encode_text("Bot Chat"))).mappings().first()
    fields = {"last_session": None, "worker_session": None, "canonical_session": None}
    if canonical and (operator or same_owner(canonical["user_id"], subject)) and not canonical["archived"]:
        fields["canonical_session"] = _summary(conn, scope, canonical)
    filters = [owned, local, sessions.c.archived == 0, sessions.c.hidden == 0,
        ~func.coalesce(sessions.c.source, "").in_(INTERNAL_LISTING_SOURCES)]
    if not operator:
        filters.append(sessions.c.user_id == subject)
    recent = func.coalesce(sessions.c.last_activity_at, sessions.c.started_at)
    latest = conn.execute(select(*columns).where(*filters).order_by(recent.desc()).limit(1)).mappings().first()
    if latest:
        fields["last_session"] = _summary(conn, scope, latest)
    worker = conn.execute(select(sessions.c.id, sessions.c.source, sessions.c.title, recent.label("last_active")).where(
        owned, func.coalesce(sessions.c.source, "").in_(INTERNAL_LISTING_SOURCES), sessions.c.archived == 0,
        sessions.c.hidden == 0).order_by(recent.desc()).limit(1)).mappings().first()
    if worker:
        fields["worker_session"] = {"id": worker["id"], "source": (worker["source"] or "").strip().lower(),
            "title": decode_text(worker["title"]) or "", "last_active": worker["last_active"] or 0}
    return fields


def _summary(conn, scope, root):
    tip = lineage(conn, scope, root["id"])[-1]
    target = conn.execute(select(*[sessions.c[name] for name in _FIELDS]).where(
        sessions.c.store_id == scope.require_store_id(), sessions.c.id == tip)).mappings().first() or root
    raw = conn.scalar(select(messages.c.content).where(messages.c.store_id == scope.require_store_id(),
        messages.c.session_id == tip, messages.c.active == 1, messages.c.role.in_(("user", "assistant")),
        func.trim(func.coalesce(messages.c.search_content, "")) != "").order_by(messages.c.id.desc()).limit(1))
    text = " ".join(str(content_from_bytes(raw) or "").split()) if raw is not None else ""
    return {"id": root["id"], "resolved_id": tip, "title": decode_text(target["title"]) or "",
        "root_title": decode_text(root["title"]) or "", "preview": text[:80] + "..." if len(text) > 80 else text,
        "started_at": target["started_at"] or 0, "last_active": target["last_activity_at"] or target["started_at"] or 0,
        "message_count": target["message_count"] or 0}
