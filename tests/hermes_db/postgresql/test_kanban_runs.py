"""Real PG run identity, competing processes and late-worker fencing."""

import json
import os
import subprocess
import sys
import time

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_dispatch as dispatch

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_claim_run_and_heartbeat_keep_one_identity(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="claim", workspace_kind="scratch", assignee="coder")
        claim = kb.claim_task(store, task_id, claimer="host:owner", ttl_seconds=60)
        assert claim is not None and claim.status == "running"
        assert kb.claim_task(store, task_id, claimer="host:loser") is None
        run = kb.get_run(store, claim.current_run_id)
        assert run.task_id == task_id and run.profile == "coder"
        assert run.claim_lock == claim.claim_lock == "host:owner"
        assert len(kb.list_runs(store, task_id)) == 1
        assert dispatch.heartbeat_worker(store, task_id, expected_run_id=run.id)
        assert kb.get_run(store, run.id).last_heartbeat_at is not None
        assert not dispatch.heartbeat_worker(store, task_id, expected_run_id=run.id + 1)


def test_two_processes_claim_once_and_restart_reads_same_run(pg_profiles, tmp_path):
    with pg_profiles("one") as home, kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="compete", workspace_kind="scratch")
        code = r'''
import json, sqlite3, sys, time
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError('SQLite in PG Kanban claim child')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
ready, gate = Path(sys.argv[3]), Path(sys.argv[4])
ready.touch()
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() > deadline:
        raise TimeoutError('claim start gate')
    time.sleep(.01)
with kbc.connect_closing() as store:
    task = kb.claim_task(store, sys.argv[2], claimer='child:' + sys.argv[5])
    print(json.dumps({'run_id': task.current_run_id if task else None}))
'''
        gate = tmp_path / "start"
        ready = [tmp_path / f"ready-{index}" for index in range(2)]
        children = [subprocess.Popen([sys.executable, "-c", code, str(home), task_id, str(ready[index]), str(gate), str(index)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for index in range(2)]
        try:
            deadline = time.monotonic() + 20
            while not all(path.exists() for path in ready):
                assert time.monotonic() < deadline, "claim children did not start"
                time.sleep(.01)
            gate.touch()
            runs = []
            for child in children:
                stdout, stderr = child.communicate(timeout=30)
                assert child.returncode == 0, stderr
                runs.append(json.loads(stdout)["run_id"])
            winner = next(run for run in runs if run is not None)
            assert sum(run is not None for run in runs) == 1
            assert kb.get_task(store, task_id).current_run_id == winner
            assert [run.id for run in kb.list_runs(store, task_id)] == [winner]
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)


def test_reclaimed_run_cannot_heartbeat_successor(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="fenced", workspace_kind="scratch")
        old = kb.claim_task(store, task_id)
        assert kb.reclaim_task(store, task_id, reason="operator retry")
        new = kb.claim_task(store, task_id)
        assert old.current_run_id != new.current_run_id
        assert kb.goal_run_status(store, task_id, old.current_run_id) == "superseded"
        assert kb.goal_run_status(store, task_id, new.current_run_id) == "running"
        assert not dispatch.heartbeat_worker(store, task_id, expected_run_id=old.current_run_id)
        assert kb.get_run(store, old.current_run_id).outcome == "reclaimed"
        assert kb.get_run(store, new.current_run_id).last_heartbeat_at is None
        assert kb._retry_status_for_run(store, task_id) == "ready"


def test_block_dependencies_sticky_resume_and_loop_limit(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="parent", workspace_kind="scratch")
        child = kb.create_task(store, title="child", workspace_kind="scratch")
        running = kb.claim_task(store, child)
        kb.link_tasks(store, parent, child, expected_child_run_id=running.current_run_id)
        assert kb.block_task(store, child, kind="dependency", reason="waiting", expected_run_id=running.current_run_id)
        assert kb.get_task(store, child).status == "todo"
        assert kb.get_run(store, running.current_run_id).outcome == "blocked"
        assert not dispatch.heartbeat_worker(store, child, expected_run_id=running.current_run_id)
        assert kb.unlink_tasks(store, parent, child)
        assert kb.get_task(store, child).status == "ready"
        for recurrence in range(kb.BLOCK_RECURRENCE_LIMIT):
            run = kb.claim_task(store, child)
            assert kb.block_task(store, child, kind="dependency", expected_run_id=run.current_run_id)
            task = kb.get_task(store, child)
            assert task.block_kind == "needs_input"
            assert task.block_recurrences == recurrence + 1
            assert kb.recompute_ready(store) == 0
            if recurrence + 1 < kb.BLOCK_RECURRENCE_LIMIT:
                assert task.status == "blocked"
                assert kb.unblock_task(store, child)
            else:
                assert task.status == "triage"


def test_pid_publication_and_adoption_keep_actual_process_fingerprint(pg_profiles):
    from hermes_db.domains.kanban.postgres import runs as run_repo
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="pid", workspace_kind="scratch")
        run = kb.claim_task(store, tid)
        fingerprint = dispatch._process_fingerprint(os.getpid())
        assert fingerprint is not None
        assert dispatch.adopt_worker_pid(store, tid, run.current_run_id, os.getpid())
        assert kb.get_task(store, tid).worker_pid == os.getpid()
        with store.read() as conn:
            assert run_repo.get(conn, store, run.current_run_id)["worker_started_at"] == fingerprint
        dispatch._set_worker_pid(store, tid, os.getpid(), run_id=run.current_run_id, claim_lock=run.claim_lock)
        assert kb.get_run(store, run.current_run_id).worker_pid == os.getpid()
        assert not dispatch.adopt_worker_pid(store, tid, run.current_run_id + 1, os.getpid())
        assert kb.complete_task(store, tid, result="done", expected_run_id=run.current_run_id)


def test_old_pid_publication_cannot_replace_successor(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="late pid", workspace_kind="scratch")
        old = kb.claim_task(store, tid)
        assert kb.reclaim_task(store, tid)
        new = kb.claim_task(store, tid)
        dispatch._set_worker_pid(store, tid, os.getpid(), run_id=old.current_run_id, claim_lock=old.claim_lock)
        assert kb.get_task(store, tid).current_run_id == new.current_run_id
        assert kb.get_task(store, tid).worker_pid is None
        assert not dispatch.adopt_worker_pid(store, tid, old.current_run_id, os.getpid())
