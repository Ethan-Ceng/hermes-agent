"""Detached crash classification followed by one atomic close/accounting transaction."""

import time
from collections import Counter

from sqlalchemy import select

from hermes_db.domains.kanban.postgres.operations.failures import record_failure
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo, evidence as evidence_repo
from hermes_db.tables.kanban import runs


def _prepare(store, board):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch, kanban_owner_recovery as recovery
    prepared = []
    now = time.time()
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if not task["worker_pid"] or not (task["claim_lock"] or "").startswith(kb._host_prefix()):
            continue
        started = task["started_at"]
        if started is not None and now - started < kb._resolve_crash_grace_seconds():
            continue
        if kb._worker_alive(task["worker_pid"], task["worker_started_at"]):
            continue
        if recovery.owner_reclaim_blocked(evidence, task["id"], crash_sweep=True):
            continue
        code = recovery.managed_run_exit_code(evidence, task["id"], task["worker_pid"], task["claim_lock"])
        dead = dispatch._classify_dead_worker(task["worker_pid"], task["claim_lock"], code, task_id=task["id"], board=board)
        recovery.apply_attempt_note(evidence, task["id"], task["worker_pid"], dead)
        prepared.append((evidence, dead))
    return prepared


def _violation_streak(conn, store, task_id):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    rows = conn.execute(select(runs.c.outcome, runs.c.error, runs.c.metadata).where(repo.key(store, task_id, runs),
        runs.c.ended_at.is_not(None)).order_by(runs.c.id.desc()).limit(dispatch._PROTOCOL_VIOLATION_SCAN_LIMIT)).mappings()
    streak = 0
    for raw in rows:
        row = repo.decode_record(raw)
        if row["outcome"] == "rate_limited":
            continue
        head = (row["error"] or "").partition(dispatch.WORKER_OUTPUT_SEP)[0]
        if row["outcome"] != "crashed" or not (kb._json_dict(row["metadata"]).get("protocol_violation")
                                                or "protocol violation" in head):
            break
        streak += 1
    return streak


def _charge(conn, store, task, dead, frequencies):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    if dead.rate_limited:
        return False
    extra = {"pid": task["worker_pid"], "claimer": task["claim_lock"]}
    limit, force = kb.DEFAULT_FAILURE_LIMIT, False
    if dead.protocol_violation:
        streak = _violation_streak(conn, store, task["id"])
        limit = int(task["max_retries"]) if task["max_retries"] is not None else dispatch._PROTOCOL_VIOLATION_FAILURE_LIMIT
        if streak < limit:
            return False
        force = True
        extra.update(protocol_violations=streak, protocol_violation_limit=limit)
    elif dead.terminal_provider:
        force = True
        extra["terminal_provider"] = True
    elif frequencies[dispatch._error_fingerprint(dead.error_text)] >= 3:
        limit = 1
        extra["sticky"] = True
    return record_failure(conn, store, repo.require_task(conn, store, task["id"]), dead.error_text, outcome="crashed",
                          failure_limit=limit, force_trip=force, event_payload_extra=extra)


def _close(conn, store, evidence, dead, frequencies):
    task = evidence.task
    retry = run_repo.retry_status(conn, store, task["id"], task["current_run_id"])
    dead.event_payload["retry_status"] = retry
    repo.task_update(conn, store, task["id"], status=retry, claim_lock=None, claim_expires=None,
                     worker_pid=None, worker_started_at=None)
    run_id = run_repo.close_run(conn, store, task, outcome=dead.run_outcome, error=dead.error_text, metadata=dead.event_payload)
    repo.event(conn, store, task["id"], dead.event_kind, dead.event_payload, run_id)
    if dead.rate_limited or dead.protocol_violation:
        repo.task_update(conn, store, task["id"], last_failure_error=dead.error_text[:500])
    blocked = _charge(conn, store, task, dead, frequencies)
    hook = dict(task_id=task["id"], assignee=task["assignee"], run_id=run_id, worker_pid=task["worker_pid"],
                exit_kind=dead.kind, exit_code=dead.code, outcome=dead.run_outcome, retry_status=retry)
    return blocked, hook


def detect_crashed_workers(store, board=None):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    prepared = _prepare(store, store.slug if board is None else board)
    crashed, limited, blocked, hooks = [], [], [], []
    if prepared:
        with store.write() as conn:
            accepted = [(evidence, dead) for evidence, dead in prepared if evidence_repo.unchanged(conn, store, evidence)]
            frequencies = Counter(dispatch._error_fingerprint(dead.error_text) for _, dead in accepted if not dead.rate_limited)
            for evidence, dead in accepted:
                tripped, hook = _close(conn, store, evidence, dead, frequencies)
                (limited if dead.rate_limited else crashed).append(evidence.task["id"])
                if tripped:
                    blocked.append(evidence.task["id"])
                hooks.append(hook)
    dispatch.detect_crashed_workers._last_auto_blocked = blocked
    dispatch.detect_crashed_workers._last_rate_limited = limited
    if kb._kanban_observer_consumed("on_kanban_worker_exited"):
        for hook in hooks:
            kb._fire_kanban_lifecycle_hook("on_kanban_worker_exited", hook.pop("task_id"), board=store.slug, **hook)
    return crashed
