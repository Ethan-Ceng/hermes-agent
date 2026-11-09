"""Bounded-lifetime retry evidence and permanent derived identity fences."""

import json
import re
import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import retirement_fences as fences
from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries.gateway import marker
from hermes_db.tables.conversations import sessions
from hermes_state_local import POLICY_PREFIX
from hermes_state_mutation_retirement import RETIRED_PREFIX, RETRY_HORIZON_S, ROUTE_FENCE_PREFIX
from hermes_state_terminal import ADMISSION_PREFIX, RESULT_PREFIX, WORKER_PREFIX, identity_key


def conversations(conn, scope):
    members, derived = {}, set()
    for _, raw in fences._prefixed(conn, scope, POLICY_PREFIX):
        receipt = marker(raw)
        if receipt is None:
            continue
        entry, lineage = receipt.get("entry"), receipt.get("lineage")
        ids = tuple(sid for sid in [receipt.get("session_id"), *(lineage if isinstance(lineage, list) else []),
            entry.get("session_id") if isinstance(entry, dict) else None] if isinstance(sid, str))
        members.update(dict.fromkeys(ids, ids))
        if str(receipt.get("request_id") or "").startswith(("bot-chat:", "a2a:")):
            derived.update(ids)
    return members, derived


def derived_api(conn, scope, session_ids):
    rows = conn.execute(select(sessions.c.id, sessions.c.source).where(sessions.c.store_id == scope.require_store_id(),
        sessions.c.id.in_(session_ids), sessions.c.source.in_(("bot_room", "api_server"))))
    return {sid for sid, source in rows if source == "bot_room" or re.fullmatch(r"api-[0-9a-f]{16}", sid)}


def prune(conn, scope, older_than=RETRY_HORIZON_S):
    cutoff, gone = time.time() - older_than, []
    for prefix in (ADMISSION_PREFIX, WORKER_PREFIX, RETIRED_PREFIX, ROUTE_FENCE_PREFIX):
        for key, raw in fences._prefixed(conn, scope, prefix):
            value = marker(raw)
            if value is None or value.get("retired_at", float("inf")) >= cutoff:
                continue
            if prefix in (RETIRED_PREFIX, ROUTE_FENCE_PREFIX) and not value.get("expires"):
                continue
            gone.append(key)
            if prefix == ADMISSION_PREFIX:
                gone.extend([RESULT_PREFIX + value["admission_id"],
                    identity_key(value["principal_id"], value["target_session_id"], value["request_id"])])
    for start in range(0, len(gone), 1000):
        fences._delete_meta(conn, scope, gone[start:start + 1000])


def keep_passed(conn, scope, derive, session_id):
    generation = 0
    while (sid := derive(generation)) != session_id:
        raw = runtime.meta(conn, scope, RETIRED_PREFIX + sid)
        if raw is None:
            return False
        value = json.loads(raw)
        value.pop("expires", None)
        runtime.set_meta(conn, scope, RETIRED_PREFIX + sid, json.dumps(value))
        generation += 1
    return True


def has_receipt(conn, scope, principal_id, session_id, request_id):
    from hermes_state_runtime import _text, mutation_receipt_key
    for value in (principal_id, session_id, request_id):
        _text(value)
    key, _ = mutation_receipt_key(principal_id, session_id, request_id, operation="model", payload={}, expected_revision=0)
    return runtime.meta(conn, scope, key) is not None
