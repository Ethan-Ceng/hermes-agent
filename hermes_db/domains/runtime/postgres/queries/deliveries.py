"""Scoped obligations, lease predicates and exact-claim conditional transitions."""

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.gateway import delivery_obligations as table
from hermes_db.core.values import decode_text


def where(scope, oid=None):
    conditions = [table.c.store_id == scope.require_store_id()]
    if oid is not None:
        conditions.append(table.c.obligation_id == oid)
    return and_(*conditions)


def row(conn, scope, oid):
    found = conn.execute(select(table).where(where(scope, oid))).mappings().one_or_none()
    return business_row(found) if found else None


def business_row(raw):
    result = dict(raw)
    for name in ("content", "last_error"):
        result[name] = decode_text(result[name])
    result.pop("store_id", None)
    return result


def record(conn, scope, values):
    conn.execute(insert(table).values(store_id=scope.require_store_id(), **values)
        .on_conflict_do_nothing(index_elements=list(table.primary_key.columns)))
    return row(conn, scope, values["obligation_id"])


def reply_recorded_since(conn, scope, session_key, content, since):
    return conn.scalar(select(table.c.obligation_id).where(where(scope), table.c.session_key == session_key,
        table.c.content == content, table.c.created_at >= since).limit(1)) is not None


def unsettled(conn, scope, *conditions):
    return [business_row(raw) for raw in conn.execute(select(table).where(where(scope),
        table.c.state.in_(("pending", "attempting", "failed")), *conditions)
        .order_by(table.c.created_at, table.c.obligation_id)).mappings()]


def owned(scope, proof):
    return and_(where(scope, proof.obligation_id), table.c.owner_instance_id == proof.instance_id, table.c.claim_token == proof.token)


def update_owned(conn, scope, proof, values, *conditions):
    return conn.execute(table.update().where(owned(scope, proof), *conditions).values(**values)).rowcount > 0


def available(instance_id, now):
    return or_(table.c.owner_instance_id.is_(None), and_(table.c.owner_instance_id != instance_id,
        or_(table.c.claim_expires_at.is_(None), table.c.claim_expires_at <= now)))


def claim(conn, scope, oid, values, *conditions):
    return conn.execute(table.update().where(where(scope, oid), *conditions).values(**values)).rowcount > 0


def prune(conn, scope, now, retention, maximum):
    conn.execute(table.delete().where(where(scope), table.c.state.in_(("delivered", "abandoned")), table.c.updated_at < now - retention))
    count = conn.scalar(select(func.count()).select_from(table).where(where(scope)))
    if count > maximum:
        ids = conn.execute(select(table.c.obligation_id).where(where(scope)).order_by(
            case((table.c.state == "delivered", 0), (table.c.state == "abandoned", 1), else_=2), table.c.updated_at, table.c.obligation_id)
            .limit(count - maximum)).scalars().all()
        conn.execute(table.delete().where(where(scope), table.c.obligation_id.in_(ids)))
