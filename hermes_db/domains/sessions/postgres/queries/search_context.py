"""Scoped index seeks for the previous/current/next message of each search hit."""

from sqlalchemy import and_, or_, select, tuple_

from hermes_db.domains.sessions.postgres.support.message_codec import codec, content_from_bytes
from hermes_db.tables.conversations import messages
from hermes_state_search import _flatten_text


def _neighbor(target, *, before):
    neighbor = messages.alias("previous" if before else "following")
    position, pivot = tuple_(neighbor.c.timestamp, neighbor.c.id), tuple_(target.c.timestamp, target.c.id)
    ordering = (neighbor.c.timestamp.desc(), neighbor.c.id.desc()) if before else (neighbor.c.timestamp, neighbor.c.id)
    return select(neighbor.c.id).where(neighbor.c.store_id == target.c.store_id,
        neighbor.c.session_id == target.c.session_id, position < pivot if before else position > pivot).order_by(
        *ordering).limit(1).correlate(target).scalar_subquery()


def attach(conn, scope, matches):
    target, context = messages.alias("target"), messages.alias("context")
    for start in range(0, len(matches), 500):
        batch = matches[start:start + 500]
        contexts = {row["id"]: [] for row in batch}
        statement = select(target.c.id.label("match_id"), context.c.role, context.c.content).select_from(target.join(context,
            and_(target.c.store_id == context.c.store_id, or_(context.c.id == target.c.id,
                context.c.id == _neighbor(target, before=True), context.c.id == _neighbor(target, before=False)))))
        statement = statement.where(target.c.store_id == scope.require_store_id(), target.c.id.in_(contexts)).order_by(
            target.c.id, context.c.timestamp, context.c.id)
        for row in conn.execute(statement).mappings():
            value = codec._decode_content(content_from_bytes(row["content"]))
            contexts[row["match_id"]].append({"role": row["role"], "content": _flatten_text(value)[:200]})
        for row in batch:
            row["context"] = contexts[row["id"]]
