"""Dashboard operator transitions share exact task/run and descendant write fences."""

from hermes_db.domains.kanban.postgres.operations.graph import _unsatisfied
from hermes_db.domains.kanban.postgres.operations.reopen import invalidate, terminate
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo


def _parents_blocking_ready(store, task_id):
    with store.read() as conn:
        return [{name: row[name] for name in ("id", "title", "status")}
                for parent in repo.linked_ids(conn, store, task_id, parents=True)
                if (row := repo.require_task(conn, store, parent))["status"] != "done"]


def _transition(conn, store, task_id, new_status):
    previous = repo.get(conn, store, task_id)
    if previous is None:
        return None
    effective = new_status
    if previous["status"] == "running" and new_status == "ready":
        if run_repo.retry_status(conn, store, task_id, previous["current_run_id"]) == "review":
            effective = "todo" if _unsatisfied(conn, store, task_id) else "review"
    if effective == "ready" and _unsatisfied(conn, store, task_id):
        return None
    values = dict(status=effective)
    if effective != "running":
        values.update(claim_lock=None, claim_expires=None, worker_pid=None)
    repo.task_update(conn, store, task_id, **values)
    result = {"terminations": [], "invalidated": []}
    run_id = None
    if previous["status"] == "running" and effective != "running" and previous["current_run_id"]:
        run_id = run_repo.close_run(conn, store, previous, outcome="reclaimed", status="reclaimed",
            summary=f"status changed to {effective} (dashboard/direct)")
        result["terminations"].append((previous["worker_pid"], previous["claim_lock"], previous["worker_started_at"]))
    repo.event(conn, store, task_id, "status", {"status": effective, "requested_status": new_status}, run_id)
    if previous["status"] in {"done", "archived"} and effective not in {"done", "archived"}:
        retracted = invalidate(conn, store, task_id, author="dashboard")
        result["terminations"].extend(retracted["terminations"])
    return effective, result


def _set_status_direct(store, task_id, new_status):
    from hermes_cli import kanban_db as kb
    if new_status not in kb.VALID_STATUSES:
        raise ValueError("unknown task status")
    with store.write() as conn:
        changed = _transition(conn, store, task_id, new_status)
    if changed is None:
        return False
    effective, result = changed
    terminate(result)
    if effective in {"done", "ready", "review"}:
        kb.recompute_ready(store)
    return True
