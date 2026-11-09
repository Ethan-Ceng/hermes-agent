"""Closed turn-lease requests inside the worker's receipted transaction."""

import time

from hermes_db.domains.runtime.postgres.operations.worker_handlers import _fields
from hermes_db.domains.sessions.postgres.queries import leases, sessions
from hermes_db.tables.gateway import session_turn_leases
from hermes_state_runtime import RuntimeStoreError, _text


def turn(conn, scope, session_id, payload, *, action):
    required = ("holder",) if action == "release" else ("holder", "ttl_seconds")
    _fields(payload, required)
    holder = _text(payload["holder"])
    ttl = payload.get("ttl_seconds", 300)
    if type(ttl) not in (int, float) or not 0.1 <= ttl <= 3600:
        raise RuntimeStoreError("invalid_params")
    root = sessions.raw_session(conn, scope, session_id)["lineage_root_id"]
    now = time.time()
    table, key_column = session_turn_leases, "conversation_id"
    if action == "acquire":
        value = leases.claim(conn, scope, table, key_column, root, holder, now, now + ttl)[0]
    elif action == "renew":
        value = leases.renew(conn, scope, table, key_column, root, holder, now + ttl)
    else:
        leases.release(conn, scope, table, key_column, root, holder)
        value = None
    return {"value": value}
