"""Permanent deletion facts and transcript-free control receipts in one store."""

import json
import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import gateway
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.gateway import gateway_routing
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.receipts import API_BINDING_PREFIX, API_DECLARED_PREFIX, POLICY_PREFIX
from hermes_db.domains.runtime.receipts import RETIRED_PREFIX, VIEWER_CLOSE_PREFIX, entry_session_id


def retire_routes(conn, scope, session_ids, *, expiring=()):
    expiring, targets = set(expiring), set(session_ids)
    for sid in targets:
        key = RETIRED_PREFIX + sid
        raw = runtime.meta(conn, scope, key)
        existing = gateway.marker(raw)
        if sid not in expiring or raw is None or existing and existing.get("expires"):
            value = {"retired_at": time.time(), "own": True, **({"expires": True} if sid in expiring else {})}
            runtime.set_meta(conn, scope, key, json.dumps(value))
        _delete_meta(conn, scope, ["gateway.api.settings.v1." + sid, VIEWER_CLOSE_PREFIX + sid])
    for row in gateway.routing_rows(conn, scope):
        if entry_session_id(row["entry_json"]) in targets:
            conn.execute(gateway_routing.delete().where(*gateway.where(scope, row["scope"]),
                gateway_routing.c.session_key == row["session_key"]))


def retire_local(conn, scope, session_ids):
    targets, gone = set(session_ids), []
    for key, raw in _prefixed(conn, scope, POLICY_PREFIX):
        value = gateway.marker(raw)
        entry = value.get("entry") if value else None
        if isinstance(entry, dict) and entry.get("session_id") in targets:
            gone.append(key)
    gone.extend(key for key, value in _prefixed(conn, scope, API_DECLARED_PREFIX) if value in targets)
    gone.extend(API_BINDING_PREFIX + sid for sid in targets)
    _delete_meta(conn, scope, gone)


def retire_mutations(conn, scope, session_ids):
    targets = set(session_ids)
    for key, raw in _prefixed(conn, scope, "gateway.mutation.v1."):
        value = gateway.marker(raw)
        result = value.get("result") if value else None
        if not isinstance(result, dict):
            continue
        message = result.get("target_message")
        named = [result.get(name) for name in ("session_id", "target_session_id", "previous_target_session_id")]
        named.append(message.get("session_id") if isinstance(message, dict) else None)
        if targets.intersection(name for name in named if isinstance(name, str)):
            value["result"] = {key: None if key in ("target_message", "summary", "title") else item for key, item in result.items()}
            runtime.set_meta(conn, scope, key, json.dumps(value, ensure_ascii=True, allow_nan=False))


def _prefixed(conn, scope, prefix):
    return conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key.startswith(prefix, autoescape=True))).all()


def _delete_meta(conn, scope, keys):
    if keys:
        conn.execute(state_meta.delete().where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.in_(keys)))
