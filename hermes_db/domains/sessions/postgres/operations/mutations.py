"""Revision-fenced session actions and their exact retry receipts in one commit."""

import json
import time
from copy import deepcopy

from hermes_db.domains.sessions.postgres.operations import mutation_policy, retirement, retirement_guards, sessions as lifecycle, titles
from hermes_db.operations.effects import invoke
from hermes_db.domains.sessions.postgres.queries import retirement as target_repo, sessions
from hermes_db.repositories import runtime
from hermes_db.tables.conversations import sessions as table
from hermes_db.core.values import decode_text
from hermes_state_mutations import validate_action
from hermes_state_runtime import RuntimeStoreError, _json, _text, mutation_receipt_key


def replay_receipt(conn, scope, key, digest):
    raw = runtime.meta(conn, scope, key)
    if raw is None:
        return None
    receipt = json.loads(raw)
    if receipt["digest"] != digest:
        raise RuntimeStoreError("admission_conflict")
    return receipt["result"]


def save_receipt(conn, scope, key, digest, result):
    runtime.set_meta(conn, scope, key, _json({"digest": digest, "result": result}))


def mutate(conn, scope, *, epoch, principal_id, session_id, request_id, expected_revision, operation, payload,
           expected_generation=None, _live_guard=None, _authorize_write=None, _prepare_only=False, _prepared=None):
    for value in (principal_id, session_id, request_id):
        _text(value)
    if type(expected_revision) is not int or expected_revision < 0:
        raise RuntimeStoreError("invalid_params")
    validate_action(operation, payload)
    if expected_generation is not None and (type(expected_generation) is not int or expected_generation < 0):
        raise RuntimeStoreError("invalid_params")
    if operation in {"delete", "rewind", "reset", "branch", "model", "compress"} and expected_generation is None:
        raise RuntimeStoreError("invalid_params")
    payload = json.loads(_json(payload))
    key, digest = mutation_receipt_key(principal_id, session_id, request_id, operation=operation, payload=payload,
        expected_revision=expected_revision, expected_generation=expected_generation)
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    old = replay_receipt(conn, scope, key, digest)
    if old is not None:
        return old, None
    row = sessions.lock_session(conn, scope, session_id)
    if row is None and operation != "import":
        raise RuntimeStoreError("not_found")
    if (row["runtime_revision"] if row else 0) != expected_revision:
        raise RuntimeStoreError("revision_conflict")
    if expected_generation is not None and (row is None or row["runtime_generation"] != expected_generation):
        raise RuntimeStoreError("stale_generation")
    targets = target_repo.canonical_targets(conn, scope, session_id) if operation == "delete" else [session_id]
    retirement_guards.lock_targets(conn, scope, targets)
    invoke(_live_guard, conn, scope, targets)
    invoke(_authorize_write, conn, scope)
    if _prepare_only:
        snapshot = mutation_policy.local_snapshot(conn, scope, session_id)
        if operation == "branch":
            _require_idle(conn, scope, sorted({session_id, snapshot["target"]}))
        return {"snapshot": snapshot}, None
    affected, projection = _apply(conn, scope, session_id, operation, payload, targets, deepcopy(_prepared))
    event = (projection["deleted_ids"], "delete") if operation == "delete" else None
    if payload.get("archived") is True and row and not row["archived"]:
        event = (list(affected) or [session_id], "archive")
    for sid in affected:
        sessions.update_session(conn, scope, sid, {"runtime_revision": table.c.runtime_revision + 1})
    updated = sessions.raw_session(conn, scope, session_id)
    result = {"session_id": session_id, "revision": updated["runtime_revision"] if updated else expected_revision + 1,
        "execution_generation": updated["runtime_generation"] if updated else expected_generation, "operation": operation, **projection}
    save_receipt(conn, scope, key, digest, result)
    return result, event


def _apply(conn, scope, session_id, operation, payload, targets, prepared):
    if operation == "import":
        from hermes_db.integration.postgres.operations.portability import import_current
        from hermes_db.integration.transfer.portability_values import values
        if len(payload["sessions"]) > values._IMPORT_MAX_SESSIONS:
            raise RuntimeStoreError("invalid_params")
        normalized, errors = values._validate_import_payload(payload["sessions"])
        if errors or not normalized or session_id != normalized[0]["session"]["id"]:
            raise RuntimeStoreError("invalid_params")
        result = import_current(conn, scope, normalized, canonical=True)
        return set(result["imported_ids"]), result
    if operation == "compress":
        from hermes_db.domains.sessions.postgres.operations.mutation_transcript import compress
        return compress(conn, scope, session_id, payload, prepared)
    if operation == "branch":
        from hermes_db.domains.sessions.postgres.operations.mutation_branch import branch
        return branch(conn, scope, session_id, payload, prepared)
    if operation in {"reset", "rewind"}:
        from hermes_db.domains.sessions.postgres.operations import mutation_transcript
        return {"reset": mutation_transcript.reset, "rewind": mutation_transcript.rewind}[operation](conn, scope, session_id, payload)
    if operation in mutation_policy.HANDLERS:
        return mutation_policy.HANDLERS[operation](conn, scope, session_id, payload, prepared)
    if operation == "delete":
        _require_idle(conn, scope, targets)
        retirement.retire_sessions(conn, scope, targets)
        for sid in targets:
            row = sessions.raw_session(conn, scope, sid)
            if row:
                sessions.bump_generation(conn, scope, row, "session_reset")
        retirement.delete_rows(conn, scope, targets)
        return set(), {"deleted_ids": targets}
    if operation not in ("rename", "archive", "sidebar"):
        raise RuntimeStoreError("invalid_params")
    affected, result = set(), {}
    for key, value in payload.items():
        if key == "title":
            affected.update(titles.set_title_on_connection(conn, scope, session_id, value, "user"))
            result[key] = decode_text(sessions.raw_session(conn, scope, session_id)["title"])
        else:
            column = "last_read_at" if key == "unread" else key
            stored = (0.0 if value else time.time()) if key == "unread" else int(value)
            changed = lifecycle.lineage_flag(conn, scope, session_id, column, stored,
                extra={"auto_archived": 0} if key == "archived" else None)
            affected.update(changed)
            if key == 'archived' and value:
                titles.retire_bot_chat(conn, scope, changed)
            result[key] = value
    return affected, result


def _require_idle(conn, scope, targets):
    retirement_guards.require_unleased(conn, scope, targets)
