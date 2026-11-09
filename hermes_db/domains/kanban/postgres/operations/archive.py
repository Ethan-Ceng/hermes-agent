"""Archive commits its audit/run release before terminating any process or cleaning files."""

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo


def archive_task(store, task_id, *, signal_fn=None):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row["status"] == "archived":
            return False
        repo.task_update(conn, store, task_id, status="archived", claim_lock=None,
                         claim_expires=None, worker_pid=None, worker_started_at=None)
        run_id = run_repo.close_run(conn, store, row, outcome="reclaimed", status="reclaimed",
                                   summary="task archived with run still active")
        repo.event(conn, store, task_id, "archived", None, run_id)
        store.command_result(conn, True)
    if row["status"] == "running":
        termination = kb._terminate_reclaimed_worker(row["worker_pid"], row["claim_lock"],
                                                    signal_fn=signal_fn, started_at=row["worker_started_at"])
        with store.write() as conn:
            repo.event(conn, store, task_id, "archive_worker_termination", termination, run_id)
    kb.recompute_ready(store)
    kb._cleanup_workspace(store, task_id)
    return True
