"""Scoped routing records and retirement predicates on a held connection."""

import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.gateway import gateway_routing as routes
from hermes_db.tables.runtime import state_meta
from hermes_state_mutation_retirement import (
    RETIRED_PREFIX, RETRY_HORIZON_S, ROUTE_FENCE_PREFIX, entry_session_id, route_fence_key, route_namespace,
)


def where(scope, namespace=None):
    conditions = [routes.c.store_id == scope.require_store_id()]
    if namespace is not None:
        conditions.append(routes.c.scope == namespace)
    return conditions


def routing_rows(conn, scope, namespace=None):
    return [dict(row) for row in conn.execute(select(routes).where(*where(scope, namespace))).mappings()]


def marker(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def route_retired(conn, scope, session_key, entry_json, now):
    value = json.loads(entry_json)
    session_id = value.get("session_id") if isinstance(value, dict) else None
    if not isinstance(session_id, str):
        return False
    namespace = route_namespace(session_key)
    own_raw = runtime.meta(conn, scope, RETIRED_PREFIX + session_id)
    own = marker(own_raw)
    if own_raw is not None and (namespace == "main" or own is None or own.get("own") is None):
        return True
    fence_raw = runtime.meta(conn, scope, route_fence_key(namespace, session_id))
    if fence_raw is None:
        return False
    fence = marker(fence_raw)
    if fence and fence.get("expires") and fence.get("retired_at", now) < now - RETRY_HORIZON_S:
        return False
    return namespace != "main" or sessions.raw_session(conn, scope, session_id) is None


def save_route(conn, scope, namespace, key, entry_json, now):
    if route_retired(conn, scope, key, entry_json, now):
        return False
    statement = insert(routes).values(store_id=scope.require_store_id(), scope=namespace,
        session_key=key, entry_json=entry_json, updated_at=now)
    conn.execute(statement.on_conflict_do_update(index_elements=list(routes.primary_key.columns),
        set_={"entry_json": statement.excluded.entry_json, "updated_at": statement.excluded.updated_at}))
    return True


def expire_route_fences(conn, scope, now):
    rows = conn.execute(select(state_meta.c.key, state_meta.c.value).where(
        state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.startswith(ROUTE_FENCE_PREFIX, autoescape=True)))
    expired = []
    for row in rows:
        value = marker(row.value)
        if value and value.get("expires") and value.get("retired_at", now) < now - RETRY_HORIZON_S:
            expired.append(row.key)
    if expired:
        conn.execute(state_meta.delete().where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.in_(expired)))


def retire_shared(conn, scope, namespace, session_ids, *, expiring=(), now):
    expire_route_fences(conn, scope, now)
    expiring, owned = set(expiring), {}
    for session_id in session_ids:
        names = {namespace}
        if sessions.raw_session(conn, scope, session_id) is None:
            names.add("main")
        for name in names:
            key = route_fence_key(name, session_id)
            raw = runtime.meta(conn, scope, key)
            existing = marker(raw)
            if session_id in expiring and raw is not None and (existing is None or not existing.get("expires")):
                continue
            value = {"retired_at": now, **({"expires": True} if session_id in expiring else {})}
            runtime.set_meta(conn, scope, key, json.dumps(value))
        owned[session_id] = names
    for row in routing_rows(conn, scope):
        if route_namespace(row["session_key"]) in owned.get(entry_session_id(row["entry_json"]), ()):
            conn.execute(routes.delete().where(*where(scope, row["scope"]), routes.c.session_key == row["session_key"]))
