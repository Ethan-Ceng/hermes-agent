"""Expired and orphaned claims, with process/admission probes outside transactions."""

import time

from hermes_db.domains.kanban.postgres.operations import sweep_support as support
from hermes_db.domains.kanban.postgres.queries import evidence as evidence_repo


def release_stale_claims(store, *, signal_fn=None, failure_limit=None):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    now = int(time.time())
    reclaimed = 0
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        expires = task["claim_expires"]
        if expires is None or expires >= now or recovery.owner_reclaim_blocked(evidence, task["id"]):
            continue
        local = (task["claim_lock"] or "").startswith(kb._host_prefix())
        heartbeat = task["last_heartbeat_at"]
        stale = heartbeat is not None and now - heartbeat > kb.DEFAULT_CLAIM_HEARTBEAT_MAX_STALE_SECONDS
        if local and task["worker_pid"] and kb._worker_alive(task["worker_pid"], task["worker_started_at"]) and not stale:
            support.extend(store, evidence, now)
            continue
        termination = support.terminate(store, evidence, signal_fn, "ttl_expired_worker_alive")
        if termination is None:
            continue
        payload = {"stale_lock": task["claim_lock"], "worker_pid": task["worker_pid"], "claim_expires": expires,
                   "last_heartbeat_at": heartbeat, "now": now, "host_local": local, "heartbeat_stale": stale, **termination}
        result = support.finish(store, evidence, outcome="reclaimed",
            error=recovery.reclaim_error(evidence, task["id"], task["claim_lock"]), payload=payload,
            run_metadata=termination, charge=True, failure_limit=failure_limit)
        if result is None:
            continue
        reclaimed += 1
        if kb._kanban_observer_consumed("on_kanban_worker_stale_claim"):
            kb._fire_kanban_lifecycle_hook("on_kanban_worker_stale_claim", task["id"], board=store.slug,
                assignee=task["assignee"], run_id=result["run_id"], worker_pid=task["worker_pid"],
                heartbeat_stale=stale, retry_status=result["retry_status"])
    return reclaimed


def reconcile_orphaned_running(store):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    reconciled = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if task["claim_lock"] is not None and task["claim_expires"] is not None:
            continue
        if recovery.owner_reclaim_blocked(evidence, task["id"]):
            continue
        if task["worker_pid"] and kb._worker_alive(task["worker_pid"], task["worker_started_at"]):
            continue
        result = support.finish(store, evidence, outcome="reclaimed", event_kind="reconciled",
            error="orphaned running card (broken claim bookkeeping)",
            payload={"reason": "orphaned_running", "claim_lock": task["claim_lock"], "claim_expires": task["claim_expires"],
                     "worker_pid": task["worker_pid"], "now": int(time.time())},
            comment="reconciliation: card was 'running' with no valid claim (dead/gone worker) — requeued to ready")
        if result is not None:
            reconciled.append(task["id"])
    return reconciled
