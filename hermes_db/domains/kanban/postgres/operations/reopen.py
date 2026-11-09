"""Parent retraction and descendant run closure compose in the owning Board transaction."""

import time
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo


def _descendants(conn, store, task_id):
    seen, pending = set(), list(repo.linked_ids(conn, store, task_id, parents=False))
    while pending:
        child = pending.pop()
        if child not in seen:
            seen.add(child)
            pending.extend(repo.linked_ids(conn, store, child, parents=False))
    return sorted(seen)


def invalidate(conn, store, task_id, *, author):
    invalidated, terminations = [], []
    now = int(time.time())
    for child_id in _descendants(conn, store, task_id):
        row = repo.require_task(conn, store, child_id)
        previous = row["status"]
        if previous not in {"ready", "review", "running", "done"}:
            continue
        resume, run_id = "ready", None
        if previous == "review":
            resume = "review"
        elif previous == "running":
            resume = run_repo.retry_status(conn, store, child_id, row["current_run_id"])
            terminations.append((row["worker_pid"], row["claim_lock"], row["worker_started_at"]))
            run_id = run_repo.close_run(conn, store, row, outcome="reclaimed", status="todo", summary=f"ancestor {task_id} reopened")
        repo.task_update(conn, store, child_id, status="todo", completed_at=None, claim_lock=None,
            claim_expires=None, worker_pid=None, worker_started_at=None, current_run_id=None, consecutive_failures=0)
        entry = dict(id=child_id, prior_status=previous, new_status="todo", resume_status=resume)
        repo.event(conn, store, child_id, "descendant_invalidated", {"ancestor": task_id,
            **{key: value for key, value in entry.items() if key != "id"}}, run_id)
        repo.event(conn, store, child_id, "status", {"status": "todo", "reason": "ancestor_reopened",
            "parent": task_id, "previous_status": previous, "resume_status": resume}, run_id)
        repo.comment(conn, store, child_id, author, f"Invalidated: ancestor {task_id} was reopened; retracted "
            f"from '{previous}' to 'todo' (will resume via '{resume}').", now)
        invalidated.append(entry)
    return {"invalidated": invalidated, "terminations": terminations}


def terminate(result):
    from hermes_cli import kanban_db as kb
    for pid, lock, birth in result["terminations"]:
        kb._terminate_reclaimed_worker(pid, lock, started_at=birth)


def invalidate_descendants_for_parent_reopen(store, task_id, *, author):
    with store.write() as conn:
        result = invalidate(conn, store, task_id, author=author)
    terminate(result)
    return result
