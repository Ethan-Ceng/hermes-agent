"""Attempt clocks, heartbeat progress and bounded runtime recovery."""

import time

from hermes_db.domains.kanban.postgres.operations import sweep_support as support
from hermes_db.domains.kanban.postgres.queries import evidence as evidence_repo


def _elapsed(evidence, now):
    started = evidence.run.get("started_at")
    if started is None:
        started = evidence.task["started_at"]
    return None if started is None else now - started


def enforce_max_runtime(store, *, signal_fn=None):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    now = int(time.time())
    timed_out = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        limit, elapsed = task["max_runtime_seconds"], _elapsed(evidence, now)
        if limit is None or elapsed is None or elapsed < limit or not task["worker_pid"]:
            continue
        if not (task["claim_lock"] or "").startswith(kb._host_prefix()):
            continue
        if recovery.owner_reclaim_blocked(evidence, task["id"]):
            continue
        termination = support.terminate(store, evidence, signal_fn, "max_runtime_worker_alive")
        if termination is None:
            continue
        result = support.finish(store, evidence, outcome="timed_out", error=f"elapsed {elapsed}s > limit {limit}s",
            payload={"pid": task["worker_pid"], "elapsed_seconds": elapsed, "limit_seconds": limit,
                     "sigkill": termination.get("sigkill", False)}, charge=True)
        if result is not None:
            timed_out.append(task["id"])
    return timed_out


def detect_stale_running(store, *, stale_timeout_seconds=0, signal_fn=None):
    from hermes_cli import kanban_owner_recovery as recovery
    from hermes_cli.kanban_db_dispatch import _STALE_HEARTBEAT_GAP_SECONDS
    if stale_timeout_seconds <= 0:
        return []
    now = int(time.time())
    reclaimed = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        elapsed, heartbeat = _elapsed(evidence, now), task["last_heartbeat_at"]
        age = None if heartbeat is None else now - heartbeat
        if elapsed is None or elapsed < stale_timeout_seconds or (age is not None and age < _STALE_HEARTBEAT_GAP_SECONDS):
            continue
        if recovery.owner_reclaim_blocked(evidence, task["id"]):
            continue
        termination = support.terminate(store, evidence, signal_fn, "heartbeat_stale_worker_alive")
        if termination is None:
            continue
        error = (f"no heartbeat for {age}s" if age is not None else "no heartbeat ever") + f" after {elapsed}s running"
        result = support.finish(store, evidence, outcome="stale", error=error,
            payload={"elapsed_seconds": elapsed, "last_heartbeat_at": heartbeat, "heartbeat_age_seconds": age,
                     "timeout_seconds": stale_timeout_seconds, "pid": task["worker_pid"], **termination})
        if result is not None:
            reclaimed.append(task["id"])
    return reclaimed
