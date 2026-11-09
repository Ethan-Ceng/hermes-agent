"""Queue transfers and replacement bindings under the store mapping fence."""

import json

from sqlalchemy import func, select

from hermes_db.domains.runtime.postgres.queries import runtime as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as session_table
from hermes_db.tables.runtime import session_admissions
from hermes_state_keys import admission_fingerprint
from hermes_db.domains.runtime.values import RuntimeStoreError, _json, _text


def _lock_targets(conn, scope, epoch, targets, required_target):
    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    for target in sorted(set(targets)):
        if target == required_target or sessions.raw_session(conn, scope, target) is not None:
            repo.lock_target(conn, scope, target)


def _unknown(conn, scope, session_id):
    return conn.scalar(select(session_admissions.c.admission_id).where(repo.target_where(scope, session_id),
        session_admissions.c.status == "unknown").limit(1)) is not None


def rehome(conn, scope, *, epoch, old_session_id, new_session_id, principal_prefix):
    for value in (old_session_id, new_session_id, principal_prefix):
        _text(value)
    _lock_targets(conn, scope, epoch, [old_session_id, new_session_id], new_session_id)
    if _unknown(conn, scope, old_session_id):
        return []
    rows = conn.execute(select(session_admissions).where(repo.target_where(scope, old_session_id),
        session_admissions.c.status == "queued", func.substr(session_admissions.c.principal_id, 1, len(principal_prefix)) == principal_prefix)
        .order_by(session_admissions.c.seq)).mappings().all()
    for row in rows:
        digest = admission_fingerprint(canonical_target=new_session_id, payload={"input": json.loads(row["payload_json"]), "intent": row["intent"]})
        repo.update(conn, scope, row["admission_id"], target_session_id=new_session_id,
                     lineage_json=json.dumps([new_session_id]), payload_digest=digest)
    if rows:
        for target in {old_session_id, new_session_id}:
            sessions.update_session(conn, scope, target, {"runtime_revision": session_table.c.runtime_revision + 1})
    return [row["admission_id"] for row in rows]


def retarget(conn, scope, *, epoch, session_id, principal_id, old_targets, new_target):
    old_targets = set(old_targets)
    for value in (session_id, principal_id, new_target, *old_targets):
        _text(value)
    _lock_targets(conn, scope, epoch, [session_id, new_target], new_target)
    if _unknown(conn, scope, session_id):
        return []
    moved = []
    rows = conn.execute(select(session_admissions).where(repo.target_where(scope, session_id),
        session_admissions.c.status == "queued", session_admissions.c.principal_id == principal_id)
        .order_by(session_admissions.c.seq)).mappings().all()
    for row in rows:
        payload = json.loads(row["payload_json"])
        descriptor = payload.get("local_automation_v1")
        if not isinstance(descriptor, dict) or descriptor.get("target") not in old_targets:
            continue
        descriptor["target"] = new_target
        digest = admission_fingerprint(canonical_target=session_id, payload={"input": payload, "intent": row["intent"]})
        repo.update(conn, scope, row["admission_id"], payload_json=_json(payload), payload_digest=digest)
        moved.append(row["admission_id"])
    if moved:
        sessions.update_session(conn, scope, session_id, {"runtime_revision": session_table.c.runtime_revision + 1})
    return moved


def retire_replaced_input(conn, scope, admission_id, binding, *, target_session_id):
    sessions.lock_store(conn, scope)
    row = repo.admission(conn, scope, admission_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    if row["target_session_id"] != target_session_id:
        raise RuntimeStoreError("admission_conflict")
    repo.lock_target(conn, scope, target_session_id)
    row = repo.admission(conn, scope, admission_id)
    if row["status"] != "queued":
        raise RuntimeStoreError("admission_started")
    repo.update(conn, scope, admission_id, status="terminal", outcome="cancelled")
    repo.set_meta(conn, scope, binding, json.dumps(admission_id))


def check_replaced_input(conn, scope, admission_id, binding):
    saved = repo.meta(conn, scope, binding)
    if saved is None or json.loads(saved) != admission_id:
        raise RuntimeStoreError("admission_conflict")


def replace_automation(conn, scope, admission_id, session_id, replaced, *, fold=False, skip=()):
    from hermes_db.domains.runtime.receipts import FOLDED_AUTOMATION_TEXT as _FOLDED_TEXT, automation_descriptor as _descriptor
    row = repo.admission(conn, scope, admission_id)
    if row is None or row["target_session_id"] != session_id or row["status"] != "queued":
        raise RuntimeStoreError("stale_generation")
    if fold:
        later = conn.scalars(select(session_admissions.c.admission_id).where(
            repo.target_where(scope, session_id), session_admissions.c.status == "queued", session_admissions.c.seq > row["seq"]))
        if any(other not in skip for other in later):
            raise RuntimeStoreError("stale_generation")
        payload = json.loads(row["payload_json"])
        payload["text"] = _FOLDED_TEXT
        _descriptor(payload).pop("identities", None)
        repo.update(conn, scope, admission_id, payload_json=json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    repo.update(conn, scope, admission_id, status="terminal", outcome="cancelled")
    replaced[:] = [admission_id]
