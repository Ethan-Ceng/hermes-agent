"""Real PG ticks, durable cross-Board capacity and renewable dispatch ownership."""

import json
import subprocess
import sys
import time

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_dispatch as dispatch
from hermes_db.errors import StorageBusyError
from hermes_db.domains.kanban.postgres.operations.dispatch_lease import DispatchLease, hold_dispatch_lease
from hermes_db.domains.kanban.postgres.queries import kanban as repo

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def dispatcher(monkeypatch):
    monkeypatch.setattr(dispatch, "_profile_exists_fn", lambda: lambda name: name in {"coder", "reviewer"})
    monkeypatch.setattr(dispatch, "_memory_pressure_level", lambda *args: "normal")
    monkeypatch.setattr(dispatch, "review_dispatch_enabled", lambda: True)
    return dispatch


def test_tick_claims_and_prepares_files_outside_connections(pg_profiles, dispatcher):
    with pg_profiles("one"), kbc.connect_closing() as store:
        first = kb.create_task(store, title="implement", assignee="coder", workspace_kind="scratch")
        second = kb.create_task(store, title="review", assignee="reviewer", workspace_kind="scratch")
        with store.write() as conn:
            repo.task_update(conn, store, second, status="review")
        calls = []

        def spawn(task, workspace, board=None):
            from pathlib import Path
            assert store._transactions.engine.pool.checkedout() == 0
            assert Path(workspace).is_dir()
            assert board == store.slug
            calls.append(task.id)
            if task.id == second:
                assert "sdlc-review" in task.skills

        result = dispatcher.dispatch_once(store, spawn_fn=spawn, max_spawn=1)
        assert [row[0] for row in result.spawned] == [second]
        assert calls == [second]
        assert kb.get_task(store, first).status == "ready"
        assert kb.get_task(store, second).status == "running"
        assert kb.latest_run(store, second).profile == "reviewer"
        assert dispatcher.dispatch_once(store, spawn_fn=spawn, max_spawn=1).spawned == []


@pytest.mark.parametrize("body_failed", [False, True])
def test_lease_release_failure_preserves_unknown_primary_commit(pg_profiles, monkeypatch, body_failed):
    from hermes_db.errors import StorageUnavailableError, UnknownCommitError
    primary = UnknownCommitError("original command outcome is unknown")

    def unavailable(lease):
        raise StorageUnavailableError("release unavailable")

    monkeypatch.setattr(DispatchLease, "release", unavailable)
    with pg_profiles("one"), kbc.connect_closing() as store:
        expected = UnknownCommitError if body_failed else StorageUnavailableError
        with pytest.raises(expected) as caught:
            with hold_dispatch_lease(store):
                if body_failed:
                    raise primary
        if body_failed:
            assert caught.value is primary
            assert any("release" in note for note in primary.__notes__)
        assert store._transactions.engine.pool.checkedout() == 0


def test_operator_reclaim_during_workspace_preparation_fences_old_spawn(pg_profiles, dispatcher, monkeypatch):
    from hermes_db.domains.kanban.postgres.operations import dispatch_lane as kanban_dispatch_lane
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="operator race", assignee="coder", workspace_kind="scratch")
        prepare = kanban_dispatch_lane._workspace
        replacement = []

        def prepare_and_replace(store, task):
            path = prepare(store, task)
            assert kb.reclaim_task(store, task.id)
            replacement.append(kb.claim_task(store, task.id, claimer="operator").current_run_id)
            return path

        monkeypatch.setattr(kanban_dispatch_lane, "_workspace", prepare_and_replace)
        calls = []
        result = dispatcher.dispatch_once(store, spawn_fn=lambda *args, **kwargs: calls.append(args[0].id), max_spawn=1)
        assert result.spawned == [] and calls == []
        assert kb.get_task(store, task_id).current_run_id == replacement[0]


def test_lease_renews_during_wait_without_retaining_pool_connection(pg_profiles, monkeypatch):
    from sqlalchemy import func, select
    from hermes_db.domains.kanban.postgres.operations import dispatch_lease as coordination
    from hermes_db.tables.kanban_dispatch import dispatch_leases
    from tests.waiting import wait_until
    monkeypatch.setattr(coordination, "LEASE_SECONDS", 2)
    monkeypatch.setattr(coordination, "RENEW_SECONDS", .1)
    with pg_profiles("one"), kbc.connect_closing() as store:
        renew = coordination.DispatchLease.renew
        observed = []

        def scoped_renew(lease):
            from hermes_constants import get_hermes_home
            observed.append(get_hermes_home())
            renew(lease)

        monkeypatch.setattr(coordination.DispatchLease, "renew", scoped_renew)
        with hold_dispatch_lease(store) as lease:
            with store.read() as conn:
                initial_deadline = conn.scalar(select(dispatch_leases.c.lease_until).where(
                    dispatch_leases.c.store_id == store.scope.store_id))

            def initial_deadline_elapsed():
                with store.read() as conn:
                    return conn.scalar(select(func.extract("epoch", func.clock_timestamp()))) >= initial_deadline

            with pg_profiles("two"):
                wait_until(initial_deadline_elapsed, timeout=5, interval=.05, what="initial lease deadline elapsed")
                lease.check()
                assert not DispatchLease(store).acquire()
                assert observed and all(home == store.scope.profile_home for home in observed)
        assert store._transactions.engine.pool.checkedout() == 0


def test_lease_blocks_sibling_board_and_expired_owner_cannot_release_successor(pg_profiles, dispatcher):
    from sqlalchemy import update
    from hermes_db.tables.kanban_dispatch import dispatch_leases
    with pg_profiles("one"):
        kb.create_board("other")
        with kbc.connect_closing() as store, kbc.connect_closing(board="other") as other:
            with hold_dispatch_lease(store) as lease:
                assert lease is not None
                assert store._transactions.engine.pool.checkedout() == 0
                assert dispatcher.dispatch_once(other).skipped_locked
                with store.write() as conn:
                    conn.execute(update(dispatch_leases).where(dispatch_leases.c.store_id == store.scope.store_id)
                                 .values(lease_until=0))
                successor = DispatchLease(other)
                assert successor.acquire()
                with pytest.raises(StorageBusyError):
                    lease.check()
            successor.check()
            successor.release()


def test_process_tick_retains_store_capacity_across_board_and_restart(pg_profiles, dispatcher, tmp_path):
    with pg_profiles("one") as home:
        kb.create_board("other")
        with kbc.connect_closing() as store:
            first = kb.create_task(store, title="first", assignee="coder", workspace_kind="scratch")
        with kbc.connect_closing(board="other") as store:
            second = kb.create_task(store, title="second", assignee="coder", workspace_kind="scratch")
        ready, gate = tmp_path / "spawn-entered", tmp_path / "return-spawn"
        code = r'''
import json, sqlite3, sys, time
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError('SQLite opened by PG dispatcher')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from hermes_cli import kanban_db_dispatch as d, kanban_db_connect as c
d._profile_exists_fn = lambda: lambda name: name == 'coder'
d._memory_pressure_level = lambda *args: 'normal'
with c.connect_closing() as store:
    def spawn(task, workspace, board=None):
        assert store._transactions.engine.pool.checkedout() == 0
        Path(sys.argv[2]).touch()
        deadline = time.monotonic() + 20
        while not Path(sys.argv[3]).exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
    result = d.dispatch_once(store, spawn_fn=spawn, max_in_progress=1)
    print(json.dumps([row[0] for row in result.spawned]))
'''
        child = subprocess.Popen([sys.executable, "-c", code, str(home), str(ready), str(gate)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 25
            while not ready.exists():
                assert child.poll() is None, child.communicate(timeout=3)[1]
                assert time.monotonic() < deadline
                time.sleep(.01)
            with kbc.connect_closing(board="other") as other:
                assert dispatcher.dispatch_once(other, max_in_progress=1).skipped_locked
            gate.touch()
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stderr
            assert json.loads(stdout) == [first]
            with kbc.connect_closing(board="other") as other:
                result = dispatcher.dispatch_once(other, max_in_progress=1)
                assert not result.skipped_locked and result.spawned == []
                assert kb.get_task(other, second).status == "ready"
        finally:
            gate.touch()
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


def test_dead_dispatch_process_lease_expires_and_successor_takes_over(pg_profiles, tmp_path):
    with pg_profiles("one") as home, kbc.connect_closing() as store:
        ready = tmp_path / "lease-owned"
        code = r'''
import sqlite3, sys, time
from pathlib import Path
def reject(*args, **kwargs):
    raise AssertionError('SQLite opened by PG lease owner')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from hermes_cli import kanban_db_connect as c
from hermes_db.domains.kanban.postgres.operations import dispatch_lease as leases
leases.LEASE_SECONDS = 1
with c.connect_closing() as store:
    lease = leases.DispatchLease(store)
    assert lease.acquire()
    Path(sys.argv[2]).touch()
    time.sleep(90)
'''
        child = subprocess.Popen([sys.executable, "-c", code, str(home), str(ready)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 20
            while not ready.exists():
                assert child.poll() is None, child.communicate(timeout=3)[1]
                assert time.monotonic() < deadline
                time.sleep(.01)
            child.kill()
            child.communicate(timeout=10)
            successor = DispatchLease(store)
            deadline = time.monotonic() + 5
            while not successor.acquire():
                assert time.monotonic() < deadline
                time.sleep(.05)
            successor.check()
            successor.release()
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
