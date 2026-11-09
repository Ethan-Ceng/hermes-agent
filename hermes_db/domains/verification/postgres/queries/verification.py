"""Scoped evidence records; caller owns transactions and retention locking."""

import json

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.verification import verification_events as events, verification_locks as locks, verification_state as states
from hermes_db.core.values import decode_text, encode_text

EXACT_FIELDS = ("session_id", "cwd", "root", "command", "canonical_command", "output_summary")


def lock_store(conn, scope):
    store_id = scope.require_store_id()
    conn.execute(insert(locks).values(store_id=store_id).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(locks.c.store_id == store_id).with_for_update()).one()


def state_key(scope, session_id, root):
    return and_(states.c.store_id == scope.require_store_id(), states.c.session_id == encode_text(session_id),
                states.c.root == encode_text(root))


def state(conn, scope, session_id, root):
    return conn.execute(select(states).where(state_key(scope, session_id, root))).mappings().one_or_none()


def save_event(conn, scope, evidence, created_at):
    values = dict(evidence)
    values.update({key: encode_text(values[key]) for key in EXACT_FIELDS})
    return conn.scalar(events.insert().values(store_id=scope.require_store_id(), created_at=created_at, **values)
                       .returning(events.c.id))


def point_to_event(conn, scope, session_id, root, event_id, *, share):
    statement = insert(states).values(store_id=scope.require_store_id(), session_id=encode_text(session_id),
        root=encode_text(root), last_event_id=event_id, last_edit_at=None, changed_paths_json="[]")
    values = {"last_event_id": event_id, "last_edit_at": None, "changed_paths_json": "[]"}
    conn.execute(statement.on_conflict_do_update(index_elements=list(states.primary_key.columns), set_=values))
    if share:
        conn.execute(update(states).where(states.c.store_id == scope.require_store_id(), states.c.root == encode_text(root),
                                          states.c.session_id != encode_text(session_id)).values(**values))


def mark_edited(conn, scope, session_id, root, changed, edited_at):
    row = state(conn, scope, session_id, root)
    existing = json.loads(row["changed_paths_json"]) if row else []
    paths = json.dumps(sorted(set(existing) | set(changed))[-200:])
    statement = insert(states).values(store_id=scope.require_store_id(), session_id=encode_text(session_id),
        root=encode_text(root), last_edit_at=edited_at, changed_paths_json=paths)
    conn.execute(statement.on_conflict_do_update(index_elements=list(states.primary_key.columns),
                 set_={"last_edit_at": edited_at, "changed_paths_json": paths}))


def event(conn, scope, event_id):
    row = conn.execute(select(events).where(events.c.store_id == scope.require_store_id(), events.c.id == event_id)
                       ).mappings().one_or_none()
    return decode_event(row)


def decode_event(row):
    if row is None:
        return None
    result = dict(row)
    result.pop("store_id")
    result.update({key: decode_text(result[key]) for key in EXACT_FIELDS})
    return result


def shared_event(conn, scope, root, since):
    query = select(events).where(events.c.store_id == scope.require_store_id(), events.c.root == encode_text(root),
        events.c.kind == "verify", events.c.status == "passed", events.c.scope == "full")
    if since:
        query = query.where(events.c.created_at >= since)
    return decode_event(conn.execute(query.order_by(events.c.id.desc()).limit(1)).mappings().one_or_none())


def prune(conn, scope, session_id, root, *, cutoff, per_root_limit, total_limit):
    store_id = scope.require_store_id()
    referenced = select(states.c.last_event_id).where(states.c.store_id == store_id, states.c.last_event_id.is_not(None))
    unreferenced = events.c.id.not_in(referenced)
    key = and_(events.c.store_id == store_id, events.c.session_id == encode_text(session_id), events.c.root == encode_text(root))
    retained = select(events.c.id).where(key).order_by(events.c.id.desc()).limit(per_root_limit)
    conn.execute(delete(events).where(key, events.c.id.not_in(retained), unreferenced))
    old_ids = select(events.c.id).where(events.c.store_id == store_id, events.c.created_at < cutoff)
    conn.execute(delete(states).where(states.c.store_id == store_id, or_(states.c.last_edit_at < cutoff,
        and_(states.c.last_edit_at.is_(None), states.c.last_event_id.in_(old_ids)))))
    conn.execute(delete(events).where(events.c.store_id == store_id, events.c.created_at < cutoff, unreferenced))
    retained = select(events.c.id).where(events.c.store_id == store_id).order_by(events.c.id.desc()).limit(total_limit)
    conn.execute(delete(events).where(events.c.store_id == store_id, events.c.id.not_in(retained), unreferenced))
