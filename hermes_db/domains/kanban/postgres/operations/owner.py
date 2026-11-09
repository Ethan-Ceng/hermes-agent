"""Closed owner-side claim and interpreter evidence operations for trusted execution policy."""

import json
import time

from sqlalchemy import select

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo
from hermes_db.tables.kanban import events
from hermes_db.core.values import decode_text
from hermes_state_runtime import RuntimeStoreError


def _event(conn, store, task_id, run_id, kind):
    row = conn.execute(select(events.c.payload, events.c.created_at).where(repo.key(store, task_id, events),
        events.c.run_id == run_id, events.c.kind == kind.encode()).order_by(events.c.id.desc()).limit(1)).one_or_none()
    if row is None:
        return None
    payload = json.loads(decode_text(row.payload) or "{}")
    return {"payload": payload if isinstance(payload, dict) else {}, "created_at": row.created_at}


def _current(conn, store, params):
    task = repo.get(conn, store, params["task_id"])
    run = run_repo.get(conn, store, params["run_id"])
    if (task is None or run is None or task["status"] != "running" or run["status"] != "running"
            or task["current_run_id"] != params["run_id"] or run["task_id"] != task["id"]
            or task["claim_lock"] != params["claim_lock"] or run["claim_lock"] != task["claim_lock"]):
        raise RuntimeStoreError("stale_kanban_claim")
    return task, run


def inspect_claim(store, params, request_id):
    with store.read() as conn:
        task, run = _current(conn, store, params)
        admitted = _event(conn, store, task["id"], run["id"], "owner_admitted")
        if admitted is not None and admitted["payload"].get("request_id") != request_id:
            raise RuntimeStoreError("stale_kanban_claim")
        retry = run_repo.retry_status(conn, store, task["id"], run["id"])
    return task, retry


def admit_claim(store, params, receipt):
    with store.write() as conn:
        old = _event(conn, store, params["task_id"], params["run_id"], "owner_admitted")
        if old is not None:
            identity = ("storage_backend", "session_id", "request_id", "profile_home", "store_id", "target", "principal_id")
            if any(old["payload"].get(key) != receipt.get(key) for key in identity):
                raise RuntimeStoreError("stale_kanban_claim")
            return
        task, _run = _current(conn, store, params)
        repo.event(conn, store, task["id"], "owner_admitted", receipt, params["run_id"])


def bind_worker(store, params, *, pid, fingerprint):
    with store.write() as conn:
        task, _run = _current(conn, store, params)
        repo.event(conn, store, task["id"], "worker_bound", {"pid": pid, "claim_lock": params["claim_lock"],
                   "started_at": fingerprint}, params["run_id"])
        claimed = _event(conn, store, task["id"], params["run_id"], "claimed")
        payload = claimed["payload"] if claimed else {}
        expires = payload.get("expires")
        ttl = max(1, expires - claimed["created_at"]) if type(expires) is int and claimed["created_at"] else None
        return store.command_result(conn, ttl)


def _bound(conn, store, params, pid):
    event = _event(conn, store, params["task_id"], params["run_id"], "worker_bound")
    payload = event["payload"] if event else {}
    return (payload.get("pid"), payload.get("claim_lock")) == (pid, params["claim_lock"])


def record_result(store, params, *, pid, code, last_output):
    with store.write() as conn:
        if _bound(conn, store, params, pid):
            repo.event(conn, store, params["task_id"], "worker_result", {"pid": pid, "claim_lock": params["claim_lock"],
                       "exit_code": code, "last_output": last_output}, params["run_id"])
        store.command_result(conn, None)


def record_loss(store, params, reason, *, pid=None, bound=False):
    with store.write() as conn:
        task = repo.get(conn, store, params["task_id"])
        if (task is None or task["status"] != "running" or task["current_run_id"] != params["run_id"]
                or task["claim_lock"] != params["claim_lock"]):
            return
        repo.event(conn, store, task["id"], "worker_lost", {"reason": str(reason)[:200], "claim_lock": params["claim_lock"],
                   "run_id": params["run_id"], "pid": pid, "bound": bool(bound)}, params["run_id"])


def worker_result(store, params):
    with store.read() as conn:
        row = _event(conn, store, params["task_id"], params["run_id"], "worker_result")
    result = row["payload"] if row else {}
    return result if result.get("claim_lock") == params["claim_lock"] else {}


def bound_claim_live(store, params, *, pid):
    with store.read() as conn:
        try:
            task, run = _current(conn, store, params)
        except RuntimeStoreError:
            return False
        now = int(time.time())
        return (task["claim_expires"] is not None and task["claim_expires"] > now
                and run["claim_expires"] is not None and run["claim_expires"] > now
                and _bound(conn, store, params, pid))
