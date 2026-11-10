"""Recovery transitions persist exact attempts, retry phases and atomic failure accounting."""

import os
import subprocess
import sys
import time

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_dispatch as dispatch
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def claimed(store, *, review=False, **kwargs):
    task_id = kb.create_task(store, title="sweep", workspace_kind="scratch", **kwargs)
    if review:
        with store.write() as conn:
            repo.task_update(conn, store, task_id, status="review", assignee="reviewer")
    task = (kb.claim_review_task if review else kb.claim_task)(store, task_id, claimer=kb._host_prefix() + "sweep")
    return task_id, task.current_run_id


def test_expired_attempt_and_live_extension_preserve_run_accounting(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store, review=True, max_retries=2)
        with store.write() as conn:
            repo.task_update(conn, store, task_id, claim_expires=int(time.time()) - 10)
        assert kb.release_stale_claims(store) == 1
        task = kb.get_task(store, task_id)
        assert task.status == "review" and task.consecutive_failures == 1 and task.current_run_id is None
        assert kb.get_run(store, run_id).outcome == "reclaimed"
        assert kb.release_stale_claims(store) == 0
        live_id, live_run = claimed(store)
        dispatch._set_worker_pid(store, live_id, os.getpid(), run_id=live_run,
                                 claim_lock=kb.get_task(store, live_id).claim_lock)
        with store.write() as conn:
            repo.task_update(conn, store, live_id, claim_expires=int(time.time()) - 10)
        assert kb.release_stale_claims(store) == 0
        live = kb.get_task(store, live_id)
        assert live.status == "running" and live.claim_expires > time.time()
        assert kb.get_run(store, live_run).claim_expires == live.claim_expires


def test_stale_and_orphan_sweeps_close_runs_without_charging_failure(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        stale_id, stale_run = claimed(store, review=True)
        orphan_id, orphan_run = claimed(store)
        old = int(time.time()) - 20000
        with store.write() as conn:
            repo.task_update(conn, store, stale_id, started_at=old, last_heartbeat_at=old)
            run_repo.update_run(conn, store, stale_run, started_at=old)
            repo.task_update(conn, store, orphan_id, claim_lock=None)
        assert dispatch.reconcile_orphaned_running(store) == [orphan_id]
        assert kb.get_run(store, orphan_run).outcome == "reclaimed"
        assert kb.list_comments(store, orphan_id)[0].author == "dispatcher"
        assert dispatch.detect_stale_running(store, stale_timeout_seconds=100) == [stale_id]
        assert kb.get_task(store, stale_id).status == "review"
        assert kb.get_task(store, stale_id).consecutive_failures == 0
        assert kb.get_run(store, stale_run).outcome == "stale"


def test_new_owner_evidence_during_termination_prevents_old_snapshot_reclaim(pg_profiles, monkeypatch):
    from hermes_db.infra.backends.postgresql.engine import get_engine
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store)
        with store.write() as conn:
            repo.task_update(conn, store, task_id, claim_expires=int(time.time()) - 10)

        def terminate(*args, **kwargs):
            assert get_engine(store.settings.postgresql).pool.checkedout() == 0
            kb._append_event(store, task_id, "owner_admitted", {}, run_id=run_id)
            return {"host_local": True, "terminated": True, "termination_attempted": True}

        monkeypatch.setattr(kb, "_terminate_reclaimed_worker", terminate)
        assert kb.release_stale_claims(store) == 0
        assert kb.get_task(store, task_id).status == "running"
        assert kb.get_run(store, run_id).ended_at is None


def test_runtime_kills_real_worker_without_retaining_connection(pg_profiles):
    from hermes_db.infra.backends.postgresql.engine import get_engine
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store, max_runtime_seconds=1, max_retries=1)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
        try:
            task = kb.get_task(store, task_id)
            dispatch._set_worker_pid(store, task_id, child.pid, run_id=run_id, claim_lock=task.claim_lock)
            with store.write() as conn:
                run_repo.update_run(conn, store, run_id, started_at=int(time.time()) - 10)

            def signal_worker(pid, sig):
                assert get_engine(store.settings.postgresql).pool.checkedout() == 0
                assert pid == child.pid
                os.kill(pid, sig)

            assert dispatch.enforce_max_runtime(store, signal_fn=signal_worker) == [task_id]
            child.wait(timeout=10)
            assert kb.get_run(store, run_id).outcome == "timed_out"
            task = kb.get_task(store, task_id)
            assert task.status == "blocked" and task.consecutive_failures == 1
            assert dispatch.enforce_max_runtime(store) == []
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def test_recovery_failure_rolls_back_run_close_and_retry_together(pg_profiles, monkeypatch):
    from hermes_db.domains.kanban.postgres import runs as kanban_failures
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store)
        with store.write() as conn:
            repo.task_update(conn, store, task_id, claim_expires=int(time.time()) - 10)

        def unavailable(*args, **kwargs):
            raise RuntimeError("failure ledger injection")

        monkeypatch.setattr(kanban_failures, "record_failure", unavailable)
        with pytest.raises(RuntimeError, match="failure ledger injection"):
            kb.release_stale_claims(store)
        task = kb.get_task(store, task_id)
        assert task.status == "running" and task.current_run_id == run_id and task.consecutive_failures == 0
        assert kb.get_run(store, run_id).ended_at is None
        assert not any(event.kind == "reclaimed" for event in kb.list_events(store, task_id))


@pytest.mark.parametrize("exit_code,expected,failures", [(7, "crashed", 1), (0, "crashed", 0)])
def test_real_dead_worker_result_closes_one_attempt(pg_profiles, exit_code, expected, failures):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store)
        child = subprocess.Popen([sys.executable, "-c", "import time, sys; time.sleep(.5); sys.exit(int(sys.argv[1]))",
                                  str(exit_code)])
        task = kb.get_task(store, task_id)
        dispatch._set_worker_pid(store, task_id, child.pid, run_id=run_id, claim_lock=task.claim_lock)
        child.wait(timeout=10)
        with store.write() as conn:
            repo.task_update(conn, store, task_id, started_at=int(time.time()) - 1000)
        kb._append_event(store, task_id, "worker_result", {"pid": child.pid, "claim_lock": task.claim_lock,
                                                         "exit_code": exit_code}, run_id=run_id)
        assert dispatch.detect_crashed_workers(store) == [task_id]
        assert kb.get_run(store, run_id).outcome == expected
        assert kb.get_task(store, task_id).consecutive_failures == failures
        assert dispatch.detect_crashed_workers(store) == []


def test_terminal_worker_reap_keeps_exact_closed_run(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id, run_id = claimed(store)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
        try:
            task = kb.get_task(store, task_id)
            dispatch._set_worker_pid(store, task_id, child.pid, run_id=run_id, claim_lock=task.claim_lock)
            assert kb.block_task(store, task_id, reason="finished worker still exiting", expected_run_id=run_id)
            with store.write() as conn:
                run_repo.update_run(conn, store, run_id, ended_at=int(time.time()) - 1000)
            assert dispatch.reap_terminal_workers(store) == [task_id]
            child.wait(timeout=10)
            assert kb.get_run(store, run_id).worker_pid is None
            assert dispatch.reap_terminal_workers(store) == []
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def test_protocol_budget_and_rate_limit_are_distinct_durable_outcomes(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="protocol budget", workspace_kind="scratch", max_retries=2)
        for attempt in range(2):
            task = kb.claim_task(store, task_id, claimer=kb._host_prefix() + "protocol")
            child = subprocess.Popen([sys.executable, "-c", "pass"])
            child.wait(timeout=10)
            dispatch._set_worker_pid(store, task_id, child.pid, run_id=task.current_run_id, claim_lock=task.claim_lock)
            with store.write() as conn:
                repo.task_update(conn, store, task_id, started_at=int(time.time()) - 1000)
            kb._append_event(store, task_id, "worker_result", {"pid": child.pid, "claim_lock": task.claim_lock,
                                                             "exit_code": 0}, run_id=task.current_run_id)
            assert dispatch.detect_crashed_workers(store) == [task_id]
            landed = kb.get_task(store, task_id)
            assert landed.status == ("ready" if attempt == 0 else "blocked")
        assert dispatch.detect_crashed_workers._last_auto_blocked == [task_id]
        assert kb.latest_run(store, task_id).outcome == "crashed"
        limited_id, run_id = claimed(store)
        task = kb.get_task(store, limited_id)
        kb._append_event(store, limited_id, "worker_result", {"pid": child.pid, "claim_lock": task.claim_lock,
                                                            "exit_code": 75}, run_id=run_id)
        dispatch._set_worker_pid(store, limited_id, child.pid, run_id=run_id, claim_lock=task.claim_lock)
        with store.write() as conn:
            repo.task_update(conn, store, limited_id, started_at=int(time.time()) - 1000)
        assert dispatch.detect_crashed_workers(store) == []
        assert dispatch.detect_crashed_workers._last_rate_limited == [limited_id]
        assert kb.get_task(store, limited_id).consecutive_failures == 0
        assert kb.latest_run(store, limited_id).outcome == "rate_limited"
        assert dispatch.check_respawn_guard(store, limited_id) == "rate_limit_cooldown"
