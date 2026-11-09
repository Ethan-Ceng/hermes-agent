"""Attempt-scoped failure accounting; sweeps compose this under their own short write."""

from hermes_cli.kanban_failure_policy import failure_budget
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo


def _retry_failure(conn, store, task, error, outcome, failures, retry, release_claim, end_run, infrastructure):
    values = {"consecutive_failures": failures, "last_failure_error": error}
    if release_claim:
        values.update(status=retry, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
    repo.task_update(conn, store, task["id"], **values)
    if end_run:
        detail = {"failures": failures, "retry_status": retry}
        if infrastructure:
            detail["infrastructure"] = True
        run_id = run_repo.close_run(conn, store, task, outcome=outcome, status=outcome, error=error, metadata=detail)
        repo.event(conn, store, task["id"], outcome, {"error": error, **detail}, run_id)
    return False


def _trip_failure(conn, store, task, error, outcome, budget, retry, release_claim, end_run, force_trip, extra):
    failures, limit, source, _trip = budget
    values = {"consecutive_failures": failures, "last_failure_error": error}
    if task["status"] in {"running", "ready", "review"}:
        values["status"] = "blocked"
    if release_claim:
        values.update(claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
    repo.task_update(conn, store, task["id"], **values)
    payload = {"failures": failures, "effective_limit": limit, "limit_source": source, "error": error,
               "trigger_outcome": outcome, "retry_status": retry}
    run_id = None
    if end_run:
        metadata = {key: value for key, value in payload.items() if key != "error"}
        run_id = run_repo.close_run(conn, store, task, outcome="gave_up", status="gave_up", error=error, metadata=metadata)
    if force_trip:
        payload["sticky"] = True
    if extra:
        payload.update(extra)
    repo.event(conn, store, task["id"], "gave_up", payload, run_id)
    return True


def record_failure(conn, store, task, error, *, outcome, failure_limit, force_trip=False, release_claim=False,
                   end_run=False, event_payload_extra=None, infrastructure=False):
    retry = run_repo.retry_status(conn, store, task["id"], task["current_run_id"]) if release_claim else (
        "review" if task["status"] == "review" else "ready")
    budget = failure_budget(task, failure_limit, force_trip, infrastructure)
    error = error[:500]
    if not budget[3]:
        return _retry_failure(conn, store, task, error, outcome, budget[0], retry, release_claim, end_run, infrastructure)
    return _trip_failure(conn, store, task, error, outcome, budget, retry, release_claim, end_run, force_trip, event_payload_extra)


def _record_task_failure(store, task_id, error, *, outcome, failure_limit=None, force_trip=False, release_claim=False,
                         end_run=False, event_payload_extra=None, infrastructure=False, expected_run_id=None):
    from hermes_cli.kanban_db import DEFAULT_FAILURE_LIMIT
    failure_limit = DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task["status"] in {"done", "archived"}:
            return store.command_result(conn, False)
        if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
            return store.command_result(conn, False)
        if release_claim and task["status"] != "running":
            return store.command_result(conn, False)
        result = record_failure(conn, store, task, error, outcome=outcome, failure_limit=failure_limit,
            force_trip=force_trip, release_claim=release_claim, end_run=end_run,
            event_payload_extra=event_payload_extra, infrastructure=infrastructure)
        return store.command_result(conn, result)


def _clear_failure_counter(store, task_id):
    with store.write() as conn:
        repo.task_update(conn, store, task_id, consecutive_failures=0, last_failure_error=None)
