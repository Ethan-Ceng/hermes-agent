"""Reap retained terminal worker identities without keeping a database connection open."""

import os
import time

import psutil
from sqlalchemy import select

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo
from hermes_db.tables.kanban import runs


def _reap(store, run, signal_fn):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    pid, fingerprint = run["worker_pid"], run["worker_started_at"]
    if pid == os.getpid() or not (run["claim_lock"] or "").startswith(kb._host_prefix()):
        return False
    if fingerprint == dispatch.UNVERIFIED_WORKER_FINGERPRINT and kb._pid_alive(pid):
        return False
    alive = kb._worker_alive(pid, fingerprint)
    termination = None
    if alive:
        termination = kb._terminate_reclaimed_worker(pid, run["claim_lock"], signal_fn=signal_fn, started_at=fingerprint)
        if not termination["terminated"]:
            return False
    with store.write() as conn:
        if run_repo.get(conn, store, run["id"]) != run:
            return False
        run_repo.update_run(conn, store, run["id"], worker_pid=None, worker_started_at=None)
        if alive:
            repo.event(conn, store, run["task_id"], "terminal_worker_reaped",
                       {"pid": pid, "worker_started_at": fingerprint, **termination}, run["id"])
    return alive


def reap_terminal_workers(store, *, signal_fn=None):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    cutoff = int(time.time()) - dispatch.TERMINAL_WORKER_REAP_GRACE_SECONDS
    with store.read() as conn:
        rows = [repo.decode_record(row) for row in conn.execute(select(runs).where(repo.scope(runs, store),
            runs.c.ended_at <= cutoff, runs.c.worker_pid.is_not(None), runs.c.worker_started_at.is_not(None))).mappings()]
    reaped = []
    for run in rows:
        try:
            if _reap(store, run, signal_fn):
                reaped.append(run["task_id"])
        except (OSError, psutil.Error):
            kb._log.debug("kanban: terminal worker probe failed for run %s", run["id"], exc_info=True)
    return reaped
