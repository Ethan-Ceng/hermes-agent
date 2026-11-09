"""Adopt current PG lineages atomically while preserving donor history and files."""

import json
import time

from hermes_db.integration.transfer.move_values import digest, recipient_snapshot_digest, snapshot_digest
from hermes_db.integration.postgres.operations import file_grants, portability
from hermes_db.domains.sessions.postgres.operations import retirement_guards as guards
from hermes_db.integration.transfer.portability_values import values
from hermes_db.domains.sessions.postgres.queries import messages, sessions
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.integration.postgres.queries import profile_move
from hermes_db.integration.transfer.session_capabilities.portability import _export


def _key(source, sid):
    return "hermes:profile-adoption:" + digest([source.require_store_id(), sid])


def _receipt(conn, scope, source, sid):
    raw = runtime.meta(conn, scope, _key(source, sid))
    return json.loads(raw) if raw else None


def _remember(conn, scope, source, sid, snapshot):
    local = profile_move.snapshot(conn, scope, sid)
    runtime.set_meta(conn, scope, _key(source, sid), json.dumps({"digest": snapshot_digest(snapshot),
        "recipient_digest": recipient_snapshot_digest(local, len(snapshot["messages"]))}))


def _existing_matches(conn, target, source, sid, snapshot):
    receipt = _receipt(conn, target, source, sid)
    if receipt is None:
        return False
    local = profile_move.snapshot(conn, target, sid)
    return (local is not None and len(local["messages"]) >= len(snapshot["messages"])
        and receipt["digest"] == snapshot_digest(snapshot)
        and receipt.get("recipient_digest") == recipient_snapshot_digest(local, len(snapshot["messages"])))


def adopt(conn, target, source, sid, *, retire_donor):
    file_grants.lock_scopes(conn, [target, source], receivers=[source])
    if sessions.raw_session(conn, source, sid) is None:
        return {"ok": False, "adopted": False, "donor_retired": False,
            "error": f"session {sid!r} not found in donor store"}
    ids = messages.resume_lineage(conn, source, sid)
    for scope in sorted([target, source], key=lambda value: value.require_store_id()):
        guards.lock_targets(conn, scope, ids)
    guards.require_unleased(conn, source, ids)
    snapshots = {key: profile_move.snapshot(conn, source, key) for key in ids}
    for key in ids:
        profile_move.require_unledgered(conn, source, key)
    unrelated = [key for key in ids if sessions.raw_session(conn, target, key) is not None
        and _receipt(conn, target, source, key) is None]
    if unrelated:
        return {"ok": False, "adopted": False, "donor_retired": False, "imported": 0, "skipped": 0,
            "errors": [f"unrelated resident session {key}" for key in unrelated]}
    existing = {key for key in ids if sessions.raw_session(conn, target, key) is not None}
    diverged = any(not _existing_matches(conn, target, source, key, snapshots[key]) for key in existing)
    rows = [_export(conn, source, sessions.get_session(conn, source, key), include_inactive=True)
        for key in ids if key not in existing]
    normalized, errors = values._validate_import_payload(rows)
    if errors:
        return {"ok": False, "adopted": False, "donor_retired": False, "errors": errors}
    result = portability.import_current(conn, target, normalized)
    if not result["ok"]:
        return {**result, "adopted": False, "donor_retired": False}
    for key in ids:
        if key not in existing:
            file_grants.transfer(conn, source, target, snapshots[key])
            _remember(conn, target, source, key, snapshots[key])
    retired = bool(retire_donor and not diverged)
    if retired:
        for key in ids:
            sessions.update_session(conn, source, key, {"ended_at": time.time(), "end_reason": "adopted_by_profile",
                "archived": 1, "auto_archived": 0})
            _remember(conn, target, source, key, profile_move.snapshot(conn, source, key))
    return {**result, "skipped": len(existing), "skipped_ids": sorted(existing), "adopted": True, "donor_retired": retired}
