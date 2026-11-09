"""Scoped archival and exact-column cloning on the caller's locked root."""

from sqlalchemy import insert, select

from hermes_db.domains.sessions.postgres.queries import messages as repo
from hermes_db.tables.conversations import messages


def clone_rows(conn, scope, source_session, row_ids, *, target_session=None):
    if not row_ids:
        return
    target_session = target_session or source_session
    skip = {"id", "active", "compacted", "display_order"}
    columns = [column for column in messages.c if column.name not in skip]
    projection = [column if column.name != "session_id" else _target(target_session) for column in columns]
    statement = insert(messages).from_select([column.name for column in columns], select(*projection).where(
        repo.where(scope, [source_session]), messages.c.id.in_(row_ids)).order_by(messages.c.id))
    conn.execute(statement)


def _target(session_id):
    from sqlalchemy import literal
    return literal(session_id)


def archive(conn, scope, session_id, rewind_ids):
    if rewind_ids:
        conn.execute(messages.update().where(repo.where(scope, [session_id]), messages.c.id.in_(rewind_ids))
                     .values(active=0, compacted=0))
    conn.execute(messages.update().where(repo.where(scope, [session_id]), messages.c.active == 1)
                 .values(active=0, compacted=1))
