"""Closed delegation mutations sharing the verified worker's receipt stream."""

from functools import partial
import json
import time

from sqlalchemy import case, func, or_

from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
from hermes_db.domains.runtime.postgres.queries import delegations as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.gateway import async_delegations as table
from hermes_db.domains.runtime.values import VerifiedDelegationOwner, RuntimeStoreError
from hermes_db.domains.runtime.values import DELEGATION_EVENT_KEYS as _EVENT_KEYS, DELEGATION_ROUTE as _ROUTE, DELEGATION_TASK_KEYS as _TASK_KEYS, delegation_number as _number, delegation_shape as _shape, delegation_text as _text






def dispatch(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"delegation_id", "task", "dispatched_at", *_ROUTE})
    _text(payload["delegation_id"])
    _number(payload["dispatched_at"])
    if not isinstance(payload["task"], dict) or set(payload["task"]) - _TASK_KEYS:
        raise RuntimeStoreError("invalid_params")
    session = sessions.raw_session(conn, scope, session_id)
    if session is None or session["source"] not in ("cli", "tui", "gui", "tool", "oneshot"):
        raise RuntimeStoreError("unsupported_producer")
    if payload["parent_session_id"] != session_id or payload["session_key"] != (session["session_key"] or "") or (
            payload["origin_ui_session_id"] not in ("", session_id) or payload["origin_session_id"] not in ("", session_id)):
        raise RuntimeStoreError("permission_denied")
    if repo.get(conn, scope, payload["delegation_id"]) is not None:
        repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
        raise RuntimeStoreError("admission_conflict")
    repo.insert(conn, scope, dict(delegation_id=payload["delegation_id"], origin_session=payload["session_key"],
        origin_ui_session_id=payload["origin_ui_session_id"], parent_session_id=session_id, state="running",
        dispatched_at=payload["dispatched_at"], updated_at=time.time(), owner_pid=owner.pid, owner_started_at=owner.started_at,
        task_json=json.dumps(payload["task"]), origin_session_id=payload["origin_session_id"], owner_execution_id=owner.execution_id))
    return {"value": None}


def complete(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"event", "result"})
    event = payload["event"]
    if not isinstance(event, dict) or set(event) - _EVENT_KEYS or not isinstance(payload["result"], dict) or (
            event.get("type") != "async_delegation" or event.get("status") not in ("completed", "success", "error", "interrupted", "stalled", "unknown")):
        raise RuntimeStoreError("invalid_params")
    row = repo.owned(conn, scope, session_id, owner.execution_id, event.get("delegation_id"))
    if any(event.get(key, "") != (row[column] or "") for key, column in _ROUTE.items()):
        raise RuntimeStoreError("permission_denied")
    _number(event.get("completed_at"))
    if row["state"] != "running":
        raise RuntimeStoreError("admission_conflict")
    repo.update(conn, scope, row["delegation_id"], {"state": event["status"], "completed_at": event["completed_at"],
        "updated_at": time.time(), "event_json": json.dumps(event), "result_json": json.dumps(payload["result"])})
    return {"value": None}


def child(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"delegation_id", "entry"})
    row = repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
    entry = payload["entry"]
    if not isinstance(entry, dict) or type(entry.get("task_index")) is not int or entry["task_index"] < 0:
        raise RuntimeStoreError("invalid_params")
    if row["state"] != "running":
        return {"value": None}
    previous = json.loads(row["result_json"] or "{}")
    results = [item for item in previous.get("results", []) if item.get("task_index") != entry["task_index"]]
    results.append(entry)
    repo.update(conn, scope, row["delegation_id"], {"result_json": json.dumps({"results": results, "partial": True}), "updated_at": time.time()})
    return {"value": None}


def read(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"delegation_id"})
    row = repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
    columns = ("delegation_id", "origin_session", "state", "dispatched_at", "completed_at", "delivery_state", "delivery_attempts", "origin_session_id")
    return {"value": {key: row[key] for key in columns} | {"result": json.loads(row["result_json"]) if row["result_json"] else None}}


def claim(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"delegation_id", "claim_id"})
    row = repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
    _text(payload["claim_id"])
    if row["state"] in ("running", "finalizing"):
        return {"value": False}
    now = time.time()
    changed = repo.update(conn, scope, row["delegation_id"], {"delivery_claim": payload["claim_id"], "delivery_claimed_at": now,
        "delivery_attempts": table.c.delivery_attempts + 1, "updated_at": now}, table.c.delivery_state == "pending",
        or_(table.c.delivery_claim.is_(None), table.c.delivery_claimed_at < now - 300))
    return {"value": changed == 1}


def delivery(conn, scope, session_id, payload, *, owner, action):
    from tools.async_delegation import _MAX_DELIVERY_ATTEMPTS
    _shape(payload, {"delegation_id", "claim_id"})
    repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
    _text(payload["claim_id"])
    now = time.time()
    values = {"updated_at": now, "delivery_claim": None, "delivery_claimed_at": None}
    if action == "ack":
        values.update(delivery_state="delivered", delivered_at=now)
    elif action == "drop":
        values["delivery_state"] = "dropped"
    elif action == "defer":
        maximum = func.max if conn.dialect.name == "sqlite" else func.greatest
        values["delivery_attempts"] = maximum(0, table.c.delivery_attempts - 1)
    else:
        values["delivery_state"] = case((table.c.delivery_attempts >= _MAX_DELIVERY_ATTEMPTS, "dropped"), else_=table.c.delivery_state)
    return {"value": repo.update(conn, scope, payload["delegation_id"], values, table.c.delivery_state == "pending",
                                 table.c.delivery_claim == payload["claim_id"]) == 1}


def unscheduled(conn, scope, session_id, payload, *, owner):
    _shape(payload, {"delegation_id"})
    row = repo.owned(conn, scope, session_id, owner.execution_id, payload["delegation_id"])
    if row["state"] != "running" or row["result_json"] is not None:
        raise RuntimeStoreError("admission_conflict")
    conn.execute(table.delete().where(repo.where(scope, payload["delegation_id"])))
    return {"value": None}


def handlers(owner):
    if not isinstance(owner, VerifiedDelegationOwner):
        raise TypeError("Delegation handlers require verified owner identity")
    functions = {"dispatch": dispatch, "complete": complete, "child": child, "read": read, "claim": claim, "unscheduled": unscheduled}
    result = {"delegation." + name: CoreEffect(partial(function, owner=owner)) for name, function in functions.items()}
    result.update({"delegation." + action: CoreEffect(partial(delivery, owner=owner, action=action))
                   for action in ("ack", "drop", "defer", "release")})
    return result
