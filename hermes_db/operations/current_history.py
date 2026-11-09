"""Bind a current-format native transcript without copying or rewriting its prefix."""

import json

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import retirement_guards as guards
from hermes_db.domains.sessions.postgres.queries import gateway, sessions
from hermes_db.repositories import history_access, runtime
from hermes_db.tables.gateway import gateway_routing
from hermes_state_local import POLICY_PREFIX
from hermes_state_runtime import RuntimeStoreError, _json

CLAIM_PREFIX = "gateway.native_history.v1:"


def claim_value(receipt):
    return _json({key: receipt[key] for key in ("profile_id", "principal_id", "session_id", "history_session_id")})


def promote(conn, scope, *, epoch, actor, receipt, own_profile, native_transport):
    runtime.require_epoch(conn, scope, epoch)
    sid = receipt["session_id"]
    guards.lock_targets(conn, scope, [sid])
    raw = runtime.meta(conn, scope, POLICY_PREFIX + sid)
    if raw is not None:
        saved = json.loads(raw)
        if any(saved.get(k) != receipt.get(k) for k in ("principal_id", "profile_id", "history_session_id")):
            raise RuntimeStoreError("permission_denied")
        return saved
    if sid != receipt["history_session_id"] or receipt["principal_id"] != actor.subject:
        raise RuntimeStoreError("invalid_params")
    if not history_access.authorize_claim(conn, scope, actor, sid, own_profile=own_profile, native_transport=native_transport):
        raise RuntimeStoreError("permission_denied")
    row = sessions.raw_session(conn, scope, sid)
    if row["source"] not in ("cli", "tui", "gui", "desktop", "oneshot", "tool", "acp"):
        raise RuntimeStoreError("not_found")
    if sessions.compression_tip(conn, scope, sid) != sid:
        raise RuntimeStoreError("admission_conflict")
    guards.require_unleased(conn, scope, [sid])
    existing = conn.scalar(select(gateway_routing.c.entry_json).where(*gateway.where(scope, ""),
        gateway_routing.c.session_key == receipt["route"]))
    if existing is not None:
        raise RuntimeStoreError("admission_conflict")
    origin = receipt["entry"]["origin"]
    sessions.update_session(conn, scope, sid, {"session_key": receipt["route"], "chat_id": sid,
        "chat_type": "dm", "user_id": actor.subject, "origin_json": _json(origin)})
    if not gateway.save_route(conn, scope, "", receipt["route"], _json(receipt["entry"]), row["started_at"]):
        raise RuntimeStoreError("admission_conflict")
    runtime.set_meta(conn, scope, CLAIM_PREFIX + sid, claim_value(receipt))
    runtime.set_meta(conn, scope, POLICY_PREFIX + sid, _json(receipt))
    return receipt
