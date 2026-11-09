"""Prepared policy commits preserve the exact transcript and prompt cache prefix."""

import json

from sqlalchemy import func, select

from hermes_db.domains.sessions.postgres.operations import retirement_guards
from hermes_db.domains.sessions.postgres.queries import lineage, retirement, sessions
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import state_meta
from hermes_db.core.values import model_config
from hermes_db.domains.runtime.receipts import POLICY_PREFIX
from hermes_db.domains.runtime.receipts import DEFERRED_PICK_PREFIX
from hermes_db.domains.runtime.values import RuntimeStoreError, _json


def local_snapshot(conn, scope, session_id):
    raw = runtime.meta(conn, scope, POLICY_PREFIX + session_id)
    if raw is None:
        raise RuntimeStoreError("runtime_coordination_required")
    saved = json.loads(raw)
    target = lineage.validate_local_receipt(conn, scope, saved, session_id)
    targets = sorted({session_id, target})
    retirement_guards.lock_targets(conn, scope, targets)
    retirement_guards.require_unleased(conn, scope, targets, allow_queued=True)
    members = retirement.compression_members(conn, scope, [target])
    revisions = dict(conn.execute(select(table.c.id, table.c.transcript_revision).where(
        table.c.store_id == scope.require_store_id(), table.c.id.in_(members))).tuples().all())
    return {"receipt": saved, "target": target, "transcript_revisions": revisions,
            "target_revision": sessions.raw_session(conn, scope, target)["runtime_revision"]}


def validate_prepared(conn, scope, session_id, prepared):
    if not isinstance(prepared, dict) or "snapshot" not in prepared:
        raise RuntimeStoreError("runtime_coordination_required")
    current = local_snapshot(conn, scope, session_id)
    if current != prepared["snapshot"]:
        raise RuntimeStoreError("revision_conflict")
    return current


def commit_policy(conn, scope, session_id, prepared):
    snapshot = validate_prepared(conn, scope, session_id, prepared)
    saved = snapshot["receipt"]
    saved["policy"] = prepared["policy"]
    runtime.set_meta(conn, scope, POLICY_PREFIX + session_id, _json(saved))
    sessions.update_session(conn, scope, session_id, {"runtime_generation": table.c.runtime_generation + 1})
    return snapshot, sessions.raw_session(conn, scope, session_id)["runtime_generation"]


def _delete_pick(conn, scope, key):
    conn.execute(state_meta.delete().where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key == key))


def model(conn, scope, session_id, payload, prepared):
    snapshot, generation = commit_policy(conn, scope, session_id, prepared)
    selected = prepared["policy"]["model"]
    config = json.loads(prepared["policy"]["config_json"])["model"]
    target = snapshot["target"]
    current = model_config(sessions.raw_session(conn, scope, target)["model_config"])
    current["provider"] = config["provider"]
    sessions.update_session(conn, scope, target, {"model": selected, "model_config": _json(current)})
    key = DEFERRED_PICK_PREFIX + session_id
    raw = runtime.meta(conn, scope, key)
    level = json.loads(raw).get("reasoning") if raw is not None and "reasoning" not in payload else None
    if level is None:
        _delete_pick(conn, scope, key)
    else:
        runtime.set_meta(conn, scope, key, _json({"reasoning": level}))
    return {session_id, target}, {"model": selected, "provider": config["provider"], "execution_generation": generation,
                                 **({"effort": payload["reasoning"]} if "reasoning" in payload else {})}


def reasoning(conn, scope, session_id, payload, prepared):
    snapshot, generation = commit_policy(conn, scope, session_id, prepared)
    key = DEFERRED_PICK_PREFIX + session_id
    raw = runtime.meta(conn, scope, key)
    if raw is not None:
        pick = json.loads(raw)
        pick.pop("reasoning", None)
        pick.get("payload", {}).pop("reasoning", None)
        if "application_id" in pick:
            runtime.set_meta(conn, scope, key, _json(pick))
        else:
            _delete_pick(conn, scope, key)
    return {session_id, snapshot["target"]}, {"effort": payload["effort"], "execution_generation": generation}


def workspace(conn, scope, session_id, payload, prepared):
    snapshot, generation = commit_policy(conn, scope, session_id, prepared)
    cwd, git = prepared["policy"]["cwd"], prepared["git"]
    targets = set(retirement.local_members(conn, scope, session_id)) | {snapshot["target"]}
    conn.execute(table.update().where(table.c.store_id == scope.require_store_id(), table.c.id.in_(targets)).values(
        cwd=cwd, git_branch=git["branch"] or None, git_repo_root=git["root"] or None,
        git_metadata_generation=func.coalesce(table.c.git_metadata_generation, 0) + 1))
    return {session_id, snapshot["target"]}, {"cwd": cwd, "branch": git["branch"] or None,
        "git_repo_root": git["root"] or None, "execution_generation": generation}


def editor_mcp(conn, scope, session_id, payload, prepared):
    snapshot, generation = commit_policy(conn, scope, session_id, prepared)
    return {session_id, snapshot["target"]}, {"tools_changed": prepared["tools_changed"],
        "mcp_servers": prepared["mcp_servers"], "execution_generation": generation}


def edit_policy(conn, scope, session_id, payload, prepared):
    snapshot, generation = commit_policy(conn, scope, session_id, prepared)
    return {session_id, snapshot["target"]}, {"edit_approval_policy": payload["policy"], "execution_generation": generation}


HANDLERS = {"model": model, "reasoning": reasoning, "workspace": workspace, "editor_mcp": editor_mcp, "edit_policy": edit_policy}


def picks(conn, scope, session_id):
    # Current receipts are the durable picks; new branches explicitly copy their picks.
    rows = conn.execute(select(state_meta.c.value).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key.startswith("gateway.mutation.v1.", autoescape=True))).scalars()
    picked = set()
    for raw in rows:
        result = json.loads(raw)["result"]
        if result.get("session_id") == session_id and result.get("status") != "deferred" and result.get("operation") in {"model", "reasoning", "workspace"}:
            picked.add(result["operation"])
    saved = runtime.meta(conn, scope, POLICY_PREFIX + session_id)
    return picked | set(json.loads(saved).get("picks", [])) if saved else picked


def refresh(conn, scope, *, epoch, session_id, old, new, generation):
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    snapshot = local_snapshot(conn, scope, session_id)
    retirement_guards.require_unleased(conn, scope, sorted({session_id, snapshot["target"]}))
    current = sessions.raw_session(conn, scope, session_id)
    if snapshot["receipt"]["policy"] != old or current is None or current["runtime_generation"] != generation:
        raise RuntimeStoreError("revision_conflict")
    return commit_policy(conn, scope, session_id, {"snapshot": snapshot, "policy": new})[1]
