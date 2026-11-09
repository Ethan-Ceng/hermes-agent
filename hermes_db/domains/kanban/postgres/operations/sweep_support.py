"""Short atomic recovery writes, guarded by detached task/run/event evidence."""

import time

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo, evidence as evidence_repo


def finish(store, evidence, *, outcome, error, payload, charge=False, failure_limit=None, comment=None,
           run_metadata=None, event_kind=None):
    from hermes_cli import kanban_db as kb
    from hermes_db.domains.kanban.postgres.operations.failures import record_failure
    task = evidence.task
    task_id = task["id"]
    with store.write() as conn:
        if not evidence_repo.unchanged(conn, store, evidence):
            return None
        retry = run_repo.retry_status(conn, store, task_id, task["current_run_id"])
        payload = {**payload, "retry_status": retry}
        repo.task_update(conn, store, task_id, status=retry, claim_lock=None, claim_expires=None,
                         worker_pid=None, worker_started_at=None, last_heartbeat_at=None)
        run_id = run_repo.close_run(conn, store, task, outcome=outcome, error=error,
                                    metadata=payload if run_metadata is None else run_metadata)
        repo.event(conn, store, task_id, event_kind or outcome, payload, run_id)
        if comment:
            repo.comment(conn, store, task_id, "dispatcher", comment, int(time.time()))
        if charge:
            record_failure(conn, store, repo.require_task(conn, store, task_id), error, outcome=outcome,
                           failure_limit=kb.DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit)
    return {"run_id": run_id, "retry_status": retry}


def extend(store, evidence, now, *, termination=None, reason=None):
    from hermes_cli import kanban_db as kb
    task = evidence.task
    task_id = task["id"]
    deferred = termination is not None
    expires = now + (kb.RECLAIM_DEFER_GRACE_SECONDS if deferred else kb._resolve_claim_ttl_seconds())
    with store.write() as conn:
        if not evidence_repo.unchanged(conn, store, evidence):
            return
        repo.task_update(conn, store, task_id, claim_expires=expires)
        run_id = task["current_run_id"]
        if run_id is not None:
            run_repo.update_run(conn, store, run_id, claim_expires=expires)
        payload = {"reason": reason or "pid_alive", "claim_lock": task["claim_lock"], "claim_expires_now": expires}
        if deferred:
            payload.update(termination)
        else:
            payload.update(worker_pid=task["worker_pid"], claim_expires_was=task["claim_expires"],
                           last_heartbeat_at=task["last_heartbeat_at"])
        repo.event(conn, store, task_id, "reclaim_deferred" if deferred else "claim_extended", payload, run_id)


def terminate(store, evidence, signal_fn, reason):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    task = evidence.task
    result = kb._terminate_reclaimed_worker(task["worker_pid"], task["claim_lock"], signal_fn=signal_fn,
                                            started_at=task["worker_started_at"])
    if kb._worker_survived_termination(result):
        extend(store, evidence, int(time.time()), termination=result, reason=reason)
        return None
    if recovery.owner_reclaim_blocked_after_kill(evidence, task["id"], signalled=bool(result.get("termination_attempted"))):
        return None
    return result
