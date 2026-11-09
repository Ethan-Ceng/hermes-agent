"""Current receipt recovery selectors, wholly inside one owning store snapshot."""

import json

from sqlalchemy import select

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.runtime import session_admissions, state_meta
from hermes_db.domains.runtime.receipts import POLICY_PREFIX


def local_owner(conn, scope, session_id):
    row = sessions.raw_session(conn, scope, session_id)
    owner = row["chat_id"] if row else None
    if not owner or owner == session_id:
        return session_id
    try:
        raw = runtime.meta(conn, scope, POLICY_PREFIX + owner)
        lineage = json.loads(raw).get("lineage") if raw is not None else None
    except (TypeError, ValueError, AttributeError):
        return session_id
    return owner if isinstance(lineage, list) and session_id in lineage else session_id


def receipt_ids(conn, scope):
    from hermes_db.domains.runtime.receipts import VIEWER_CLOSE_PREFIX as CLOSE_PREFIX
    store_id = scope.require_store_id()
    rows = conn.execute(select(state_meta.c.key, state_meta.c.value).where(
        state_meta.c.store_id == store_id, state_meta.c.key.startswith(POLICY_PREFIX, autoescape=True)))
    receipts = {}
    for key, raw in rows:
        try:
            receipts[key[len(POLICY_PREFIX):]] = json.loads(raw)["entry"]["session_id"]
        except (ValueError, TypeError, KeyError):
            receipts[key[len(POLICY_PREFIX):]] = None  # Restore logs and refuses a malformed receipt.
    targets = sessions.get_sessions(conn, scope, [target for target in receipts.values() if target is not None])
    pending = set(conn.execute(select(session_admissions.c.target_session_id).where(
        session_admissions.c.store_id == store_id, session_admissions.c.status.in_(("queued", "started", "unknown"))))
        .scalars())
    closed = set(conn.execute(select(state_meta.c.key).where(
        state_meta.c.store_id == store_id, state_meta.c.key.startswith(CLOSE_PREFIX, autoescape=True))).scalars())
    return [owner for owner, target in receipts.items() if not targets.get(target, {}).get("ended_at")
        or targets[target]["end_reason"] == "compression" or owner in pending or CLOSE_PREFIX + owner in closed]


def unknown_inputs(conn, scope):
    return [runtime.public_row(row) for row in conn.execute(select(session_admissions).where(
        session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.status == "unknown")
        .order_by(session_admissions.c.seq)).mappings()]
