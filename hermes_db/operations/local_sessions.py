"""Current local create receipts, routes and idle closure on one scoped connection."""

from datetime import datetime
import json
import time

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import retirement_guards as guards, sessions as lifecycle
from hermes_db.domains.sessions.postgres.queries import gateway, sessions
from hermes_db.repositories import runtime
from hermes_db.tables.gateway import gateway_routing
from hermes_state_local import POLICY_PREFIX, _row_cwd, same_create_retry
from hermes_state_runtime import RuntimeStoreError, _json


def _retry(raw, receipt, request):
    try:
        saved = json.loads(raw)
        same = all(saved[name] == receipt[name] for name in ("profile_id", "principal_id", "request_id", "session_id", "route"))
        same = same and same_create_retry(saved["policy"], receipt["policy"]["request_json"], request)
    except (ValueError, TypeError, KeyError):
        raise RuntimeStoreError("storage_unavailable") from None
    if not same:
        raise RuntimeStoreError("invalid_params")
    return saved


def commit(conn, scope, *, epoch, receipt, request, own_profile, publish=None):
    from gateway.session_policy import created_surface
    from hermes_state_keys import local_identity
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    sid, route = receipt["session_id"], receipt["route"]
    if sid != local_identity(receipt["profile_id"], receipt["principal_id"], receipt["request_id"]):
        raise RuntimeStoreError("invalid_params")
    if "legacy_session_id" in receipt:
        raise RuntimeStoreError("invalid_params", detail="PostgreSQL accepts current local creation receipts only")
    raw = runtime.meta(conn, scope, POLICY_PREFIX + sid)
    if raw is not None:
        return _retry(raw, receipt, request)
    if sessions.retired_session(conn, scope, sid):
        raise RuntimeStoreError("not_found")
    if sessions.raw_session(conn, scope, sid) is not None:
        raise RuntimeStoreError("storage_unavailable")
    if conn.scalar(select(gateway_routing.c.session_key).where(*gateway.where(scope, ""), gateway_routing.c.session_key == route)) is not None:
        raise RuntimeStoreError("admission_conflict")
    policy, entry = receipt["policy"], receipt["entry"]
    started = datetime.fromisoformat(entry["created_at"]).timestamp()
    lifecycle.create_on_connection(conn, scope, sid, policy["source"], own_profile=own_profile,
        user_id=receipt["principal_id"], session_key=route, chat_id=entry["origin"]["chat_id"], chat_type="dm",
        model=policy["model"], cwd=_row_cwd(policy), origin_json=_json(entry["origin"]))
    sessions.update_session(conn, scope, sid, {"created_source": created_surface(policy["source"]), "started_at": started})
    if not gateway.save_route(conn, scope, "", route, _json(entry), started):
        raise RuntimeStoreError("not_found")
    runtime.set_meta(conn, scope, POLICY_PREFIX + sid, _json(receipt))
    if publish is not None:
        publish()
    return receipt


def idle_end(conn, scope, *, epoch, session_id, target_id, reason):
    runtime.require_epoch(conn, scope, epoch)
    guards.lock_targets(conn, scope, [session_id, target_id])
    try:
        guards.require_quiet(conn, scope, [session_id, target_id])
    except RuntimeStoreError as exc:
        if exc.reason not in ("session_busy", "unknown_execution"):
            raise
        return 0
    row = sessions.raw_session(conn, scope, target_id)
    if row is None or row["ended_at"] is not None:
        return 0
    changed = sessions.update_session(conn, scope, target_id, {"ended_at": time.time(), "end_reason": reason})
    sessions.bump_generation(conn, scope, row, reason)
    return changed
