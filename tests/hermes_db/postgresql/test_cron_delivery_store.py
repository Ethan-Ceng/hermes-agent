"""Real PG queue operations, durable terminal tombstones and no SQLite escape."""

from contextlib import contextmanager
from dataclasses import replace
import json
import sqlite3

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def queue_profiles(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_cli.config import atomic_config_write
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.schema import upgrade_schema
    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)

    @contextmanager
    def owner(name):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": {
            "schema": pg.schema, "store_id": name, "pool_size": 2, "max_overflow": 0, "connection_budget": 2}}})
        (home / ".env").write_text("HERMES_POSTGRES_DSN=" + json.dumps(pg.dsn) + "\n", encoding="utf-8")
        home_token = set_hermes_home_override(home)
        secret_token = set_secret_scope({"HERMES_POSTGRES_DSN": pg.dsn}, profile_home=str(home))
        try:
            yield home
        finally:
            reset_secret_scope(secret_token)
            reset_hermes_home_override(home_token)

    def reject(*args, **kwargs):
        pytest.fail("Cron PG delivery must reject all SQLite connections")
    monkeypatch.setattr(sqlite3, "connect", reject)
    return owner


def test_pg_delivery_contract_and_store_isolation(queue_profiles, monkeypatch):
    from cron import delivery_queue as queue
    from tests.hermes_db.contracts.test_cron_delivery_store import exercise_delivery_contract
    monkeypatch.setattr(queue, "MAX_TERMINAL_DELIVERIES", 0)
    with queue_profiles("one") as home:
        exercise_delivery_contract(queue)
        assert not (home / "cron/deliveries.db").exists()
    with queue_profiles("two"):
        assert queue.get_status("exec") is None
        assert queue.claim_next() is None


def test_gateway_watch_drains_without_file_and_send_holds_no_connection(queue_profiles):
    from cron import delivery_queue as queue
    from gateway.run_delivery_queue_watch import DeliveryQueueWatch
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.engine import get_engine

    with queue_profiles("one") as home:
        settings, _scope = resolve_db_configuration()
        pool = get_engine(settings.postgresql)
        sent = []
        def send(job, content, failure):
            assert pool.pool.checkedout() == 0
            sent.append(content)
        watch = DeliveryQueueWatch(lambda: [home], lambda: queue.drain(send))
        queue.enqueue("watched", {"id": "job"}, "persisted")
        assert watch.changed()
        assert watch.drain() == 1
        assert sent == ["persisted"]
        assert not (home / "cron/deliveries.db").exists()


def test_two_process_claim_and_crash_fences_unknown_without_retry(queue_profiles):
    import subprocess
    import sys
    from cron import delivery_queue as queue
    code = r'''
import sys, json, sqlite3
def reject(*args, **kwargs):
    raise AssertionError('SQLite in PG queue child')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from cron import delivery_queue as queue
sys.stdin.read(1)
row = queue.claim_next()
print(json.dumps({'claimed': row is not None}))
'''
    with queue_profiles("one") as home:
        queue.enqueue("crash", {"id": "job"}, "uncertain")
        children = [subprocess.Popen([sys.executable, "-c", code, str(home)], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            for child in children:
                child.stdin.write("x")
                child.stdin.flush()
            results = []
            for child in children:
                stdout, stderr = child.communicate(timeout=30)
                assert child.returncode == 0, stderr
                results.append(json.loads(stdout)["claimed"])
            assert sorted(results) == [False, True]
            assert queue.recover_abandoned() == 1
            assert queue.get_status("crash")["status"] == "unknown"
            sends = []
            assert queue.drain(lambda *args: sends.append(args)) == 0
            assert sends == []
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)


def test_finish_commit_confirmation_loss_does_not_duplicate_send(queue_profiles, monkeypatch):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from cron import delivery_queue as queue
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.engine import get_engine
    from hermes_db.errors import UnknownCommitError

    with queue_profiles("one"):
        settings, _scope = resolve_db_configuration()
        pool = get_engine(settings.postgresql)
        queue.enqueue("ack-loss", {"id": "job"}, "once")
        sends = []
        original_commit = pool.dialect.do_commit
        def lose_confirmation(connection):
            original_commit(connection)
            raise OperationalError("commit acknowledgement lost", {}, psycopg.OperationalError("connection lost"))
        with monkeypatch.context() as fault:
            def send(job, content, failure):
                sends.append(content)
                fault.setattr(pool.dialect, "do_commit", lose_confirmation)
            with pytest.raises(UnknownCommitError):
                queue.drain(send)
        assert queue.get_status("ack-loss")["status"] == "delivered"
        assert queue.drain(lambda *args: sends.append(args)) == 0
        assert sends == ["once"]


def test_active_send_tracking_is_profile_scoped(queue_profiles):
    from cron import delivery_queue as queue
    with queue_profiles("one"):
        queue.enqueue("same", {"id": "job"}, "one")
        assert queue.claim_next()["content"] == "one"
    with queue_profiles("two"):
        queue.enqueue("same", {"id": "job"}, "two")
        assert queue.claim_next()["content"] == "two"
        queue._ACTIVE_DELIVERIES.discard(queue._active_key("same"))
        assert queue.recover_abandoned() == 1
        assert queue.get_status("same")["status"] == "unknown"
    with queue_profiles("one"):
        assert queue.get_status("same")["status"] == "delivering"
        assert queue.recover_abandoned() == 0
        assert queue._finish("same", error=None)
        queue._ACTIVE_DELIVERIES.discard(queue._active_key("same"))
