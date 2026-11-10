"""Independent PG processes, uncertain commits and exact Stop completion races."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest

from gateway import hosted_room_driver as driver, hosted_rooms as rooms
from tests.hermes_db.postgresql.test_room_work import lease, prepare, snapshot

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_stop_ack_and_late_completion_compete_on_exact_generation(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        current = lease(location)
        driver.start_task(location, identity, current, expected_cancel_generation=0, clock=lambda: 10)
        driver.begin_task_cancel(location, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 10)
        gate = Barrier(2)
        def complete():
            gate.wait(15)
            try:
                return driver.settle_stopping_task(location, identity, current, expected_execution_generation=1,
                    expected_cancel_generation=1, settlement_id="result", status="settled", result={"zero": 0, "false": False}, clock=lambda: 10)
            except driver.StaleTaskError:
                return None
        def acknowledge():
            gate.wait(15)
            try:
                return driver.complete_task_cancel(location, identity, cancel_id="stop", expected_cancel_generation=1, clock=lambda: 10)
            except driver.StaleTaskError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(complete), pool.submit(acknowledge)]
            results = [future.result(30) for future in futures]
        assert sum(result is not None for result in results) == 1
        final = driver.get_task(location, identity)
        assert final["status"] in {"settled", "cancelled"}
        assert final["execution_generation"] == 1 and final["cancel_generation"] == 1
        assert snapshot()["tasks"][0]["phase"] == final["status"]


def test_lost_commit_confirmation_replays_same_settlement_and_evidence(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        attempt = driver.start_task(location, identity, lease(location), expected_cancel_generation=0, clock=lambda: 10)
        original = Transactions.write
        armed = [True]
        @contextmanager
        def lose_ack(self, *args, **kwargs):
            with original(self, *args, **kwargs) as conn:
                yield conn
            if armed[0]:
                armed[0] = False
                raise UnknownCommitError("injected room task commit confirmation loss")
        params = dict(settlement_id="receipt", status="settled", result={"text": "持久\x00🙂", "false": False, "zero": 0}, clock=lambda: 10)
        with monkeypatch.context() as patch:
            patch.setattr(Transactions, "write", lose_ack)
            with pytest.raises(UnknownCommitError):
                driver.settle_task(location, attempt, **params)
        evidence = snapshot()
        # Identical committed settlement remains replayable after lease expiry.
        repeated = driver.settle_task(location, attempt, **(params | {"clock": lambda: 100}))
        assert repeated["idempotent"] and repeated["result"] == params["result"]
        assert snapshot() == evidence and evidence["tasks"][0]["phase"] == "settled"


def test_actual_successor_processes_compete_and_recover_without_any_sqlite(pg_profiles):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        location = rooms.default_db_path()
        identity = prepare(location)
        old = lease(location)
        attempt = driver.start_task(location, identity, old, expected_cancel_generation=0, clock=lambda: 10)
        code = r'''
import sqlite3, sys
def reject(*args, **kwargs):
    raise AssertionError("SQLite rejected in PG room driver process")
sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == 'sqlite3.connect' else None)
from gateway import hosted_room_driver as driver, hosted_rooms as rooms
location = rooms.default_db_path()
sys.stdin.readline()
try:
    lease = driver.acquire_lease(location, room_id="room", gateway_id="owner", authority_epoch=1,
        process_generation=sys.argv[1], ttl_seconds=30, clock=lambda: 21)
except driver.LeaseHeldError:
    print("HELD", flush=True)
else:
    restored = driver.recover_room(location, lease, clock=lambda: 21)
    assert restored["indeterminate"] == [driver.TaskIdentity("room", "task", "thread", "turn")]
    assert driver.get_task(location, restored["indeterminate"][0])["execution_generation"] == 1
    print("RECOVERED", flush=True)
'''
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        children = [subprocess.Popen([sys.executable, "-c", code, name], cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            for name in ("successor-a", "successor-b")]
        try:
            for child in children:
                child.stdin.write("go\n")
                child.stdin.flush()
            outputs = [child.communicate(timeout=60) for child in children]
            assert all(child.returncode == 0 for child in children), [stderr for _, stderr in outputs]
            assert sorted(stdout.strip() for stdout, _ in outputs) == ["HELD", "RECOVERED"]
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
        assert driver.get_task(location, identity)["status"] == "indeterminate"
        assert snapshot()["tasks"][0]["phase"] == "indeterminate"
        with pytest.raises(driver.StaleLeaseError):
            driver.settle_task(location, attempt, settlement_id="late", status="settled", result={}, clock=lambda: 21)
    with pg_profiles("two"):
        other = rooms.default_db_path()
        with pytest.raises(driver.TaskConflictError):
            driver.get_task(other, identity)
        prepare(other)
        assert lease(other).lease_generation == 1
        assert driver.get_task(other, identity)["status"] == "queued"
        assert driver.get_task(location, identity)["status"] == "indeterminate"


def test_equal_numeric_lease_fences_do_not_authorize_another_room(pg_profiles):
    from dataclasses import replace
    with pg_profiles("one"):
        location = rooms.default_db_path()
        prepare(location)
        first = lease(location)
        rooms.create_room(location, room_id="other", name="Other", members=[{"profile": "ops", "handle": "ops"}], authority_gateway_id="owner")
        identity = driver.TaskIdentity("other", "task", "thread", "turn")
        driver.admit_task(location, identity, payload={"target_profile": "ops", "prompt": "input", "source_event_seq": 1}, clock=lambda: 10)
        second = driver.acquire_lease(location, room_id="other", gateway_id="owner", authority_epoch=1,
            process_generation="process-a", ttl_seconds=10, clock=lambda: 10)
        attempt = driver.start_task(location, identity, second, expected_cancel_generation=0, clock=lambda: 10)
        with pytest.raises(driver.DriverValidationError, match="different rooms"):
            driver.settle_task(location, replace(attempt, lease=first), settlement_id="foreign", status="settled", result={}, clock=lambda: 10)
        assert driver.get_task(location, identity)["status"] == "running"
