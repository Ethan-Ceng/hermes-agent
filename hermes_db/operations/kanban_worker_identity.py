"""Host process witnesses are captured off-connection and applied under the run fence."""

from sqlalchemy import update

from hermes_db.repositories import kanban as repo, kanban_runs as run_repo
from hermes_db.tables.kanban import tasks
from hermes_db.core.values import encode_text


def _set_worker_pid(store, task_id, pid, *, run_id=None, claim_lock=None):
    from hermes_cli.kanban_db_dispatch import _process_fingerprint, UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = _process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return
        run_id = task["current_run_id"] if run_id is None else run_id
        condition = repo.key(store, task_id) & (tasks.c.status == b"running") & tasks.c.worker_pid.is_(None)
        condition &= tasks.c.current_run_id.is_not_distinct_from(run_id)
        if claim_lock is not None:
            condition &= tasks.c.claim_lock == encode_text(claim_lock)
        changed = conn.execute(update(tasks).where(condition).values(worker_pid=int(pid),
            worker_started_at=encode_text(fingerprint))).rowcount
        if changed and run_id is not None:
            run_repo.update_run(conn, store, run_id, worker_pid=int(pid), worker_started_at=fingerprint)
        repo.event(conn, store, task_id, "spawned", {"pid": int(pid), "started_at": fingerprint}, run_id)


def adopt_worker_pid(store, task_id, run_id, pid):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_dispatch import _process_fingerprint, UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = _process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task["status"] != "running" or task["current_run_id"] != int(run_id):
            return False
        if task["worker_pid"] is None and (task["claim_lock"] or "").startswith(kb._host_prefix()):
            repo.task_update(conn, store, task_id, worker_pid=int(pid), worker_started_at=fingerprint)
            run_repo.update_run(conn, store, run_id, worker_pid=int(pid), worker_started_at=fingerprint)
            repo.event(conn, store, task_id, "worker_registered", {"pid": int(pid), "started_at": fingerprint}, int(run_id))
    return True
