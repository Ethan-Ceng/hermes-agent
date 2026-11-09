"""Current scoped identity evidence for Profile repair."""

from sqlalchemy import and_, select, union

from hermes_db.tables.conversations import sessions
from hermes_db.tables.runtime import session_admissions, worker_executions
from hermes_state_profile_repair import _stored_profile, session_key_profile


def keyed_rows(conn, scope):
    parent = sessions.alias("parent")
    return list(conn.execute(select(sessions.c.id, sessions.c.session_key, sessions.c.profile_name,
        sessions.c.parent_session_id, sessions.c.message_count, parent.c.session_key.label("parent_session_key"))
        .outerjoin(parent, and_(parent.c.store_id == sessions.c.store_id, parent.c.id == sessions.c.parent_session_id))
        .where(sessions.c.store_id == scope.require_store_id(), sessions.c.session_key.startswith("agent:", autoescape=True))
        .order_by(sessions.c.started_at, sessions.c.id)).mappings())


def ledgered_ids(conn, scope):
    return set(conn.execute(union(select(session_admissions.c.target_session_id).where(
        session_admissions.c.store_id == scope.require_store_id()), select(worker_executions.c.session_id).where(
        worker_executions.c.store_id == scope.require_store_id()))).scalars())


def crossed(conn, scope, owner):
    ledgered = ledgered_ids(conn, scope)
    found = {"mislabelled": [], "foreign": [], "crossed_parents": []}
    for row in keyed_rows(conn, scope):
        mine, theirs = session_key_profile(row["session_key"]), session_key_profile(row["parent_session_key"])
        if mine is None:
            continue
        label = _stored_profile(row["profile_name"])
        if label is not None and label != mine:
            found["mislabelled"].append(dict(id=row["id"], session_key=row["session_key"], profile_name=label, key_profile=mine))
        if mine != owner:
            found["foreign"].append(dict(id=row["id"], session_key=row["session_key"], key_profile=mine,
                message_count=int(row["message_count"] or 0), parent_session_id=row["parent_session_id"], ledgered=row["id"] in ledgered))
        if theirs is not None and theirs != mine:
            found["crossed_parents"].append(dict(id=row["id"], key_profile=mine,
                parent_session_id=row["parent_session_id"], parent_profile=theirs))
    return found
