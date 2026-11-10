"""Real execution/incident entrypoints on one selected backend, never SQLite."""

from contextlib import contextmanager
from dataclasses import replace
import json
import sqlite3

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def cron_profiles(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
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
        token = set_hermes_home_override(home)
        secret = set_secret_scope({"HERMES_POSTGRES_DSN": pg.dsn}, profile_home=str(home))
        try:
            yield home
        finally:
            reset_secret_scope(secret)
            reset_hermes_home_override(token)

    def reject(*args, **kwargs):
        pytest.fail("Cron PG operations must reject all SQLite connections")
    monkeypatch.setattr(sqlite3, "connect", reject)
    return owner


def test_execution_incident_lifecycle_isolation_and_reopen(cron_profiles):
    from cron import executions as ex, incidents as inc
    with cron_profiles("one") as home:
        claimed = ex.create_execution("same\x00🙂", source="builtin")
        assert claimed["status"] == "claimed"
        assert ex.mark_execution_running(claimed["id"])["status"] == "running"
        assert ex.touch_execution_progress(claimed["id"])
        failed = ex.finish_execution(claimed["id"], success=False, error="failure\x00", delivery_outcome="queued")
        assert failed["status"] == "failed"
        assert ex.finish_execution(claimed["id"], success=True) is None
        assert ex.settle_delivery_outcome(claimed["id"], "delivered")
        assert not ex.settle_delivery_outcome(claimed["id"], "queued")
        incident, new = inc.upsert_incident("same\x00🙂", "provider timeout 5s")
        assert new
        assert inc.set_incident_state(incident, "alerted")
        assert inc.close_incidents_for_recovered_job("same\x00🙂") == 1
        assert inc.upsert_incident("same\x00🙂", "provider timeout 7s") == (incident, True)
        assert inc.ack_incident(incident)
        assert inc.upsert_incident("same\x00🙂", "provider timeout 7s") == (incident, False)
        assert not (home / "cron/executions.db").exists()
    with cron_profiles("two"):
        assert ex.get_execution(claimed["id"]) is None
        assert inc.count_incidents() == 0
    from hermes_db.infra.backends.postgresql.engine import close_engines
    close_engines()
    with cron_profiles("one"):
        assert ex.get_execution(claimed["id"])["error"] == "failure\x00"
        assert inc.get_incident(incident)["state"] == "closed"


def test_two_real_processes_adopt_once_and_owner_cannot_overwrite(cron_profiles):
    import subprocess
    import sys
    from cron import executions as ex
    code = r'''
import sys, sqlite3, json
def reject(*args, **kwargs):
    raise AssertionError('SQLite in Cron PG child')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from cron import executions as ex
sys.stdin.read(1)
result = ex.adopt_claimed_execution(sys.argv[2])
if result is not None:
    assert ex.finish_execution(sys.argv[2], success=True)['status'] == 'completed'
print(json.dumps({'adopted': result is not None}))
'''
    with cron_profiles("one") as home:
        claimed = ex.create_execution("race", source="external")
        ex.mark_execution_handoff_pending(claimed["id"])
        children = [subprocess.Popen([sys.executable, "-c", code, str(home), claimed["id"]],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            for child in children:
                child.stdin.write("x")
                child.stdin.flush()
            outcomes = []
            for child in children:
                stdout, stderr = child.communicate(timeout=30)
                assert child.returncode == 0, stderr
                outcomes.append(json.loads(stdout)["adopted"])
            assert sorted(outcomes) == [False, True]
            assert ex.get_execution(claimed["id"])["status"] == "completed"
            assert ex.finish_execution(claimed["id"], success=False, error="late parent") is None
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)


def test_recovery_snapshot_does_not_overwrite_adoption(cron_profiles, monkeypatch):
    from sqlalchemy import update
    from cron import executions as ex
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.tables.cron import cron_executions as rows
    from hermes_db.core.values import encode_text

    with cron_profiles("one"):
        claimed = ex.create_execution("race", source="external")
        ex.mark_execution_handoff_pending(claimed["id"])
        with acquire_profile_domain("cron_executions") as resource, resource.write() as conn:
            conn.execute(update(rows).where(rows.c.store_id == "one", rows.c.id == encode_text(claimed["id"]))
                          .values(handoff_started_at=0))
        monkeypatch.setattr(ex, "_PROCESS_ID", "replacement")
        def adopt(pid, started):
            with monkeypatch.context() as owner:
                owner.setattr(ex, "_PROCESS_ID", "adopter")
                assert ex.adopt_claimed_execution(claimed["id"])["status"] == "running"
            return False
        monkeypatch.setattr(ex, "_owner_is_live", adopt)
        assert ex.recover_interrupted_executions() == 0
        assert ex.get_execution(claimed["id"])["process_id"] == "adopter"


def test_occurrence_order_and_real_connection_loss(cron_profiles, monkeypatch):
    from datetime import datetime
    from sqlalchemy import event
    from cron import executions as ex
    from cron.occurrences import completed_occurrence
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageError

    with cron_profiles("one"):
        instant = "2026-11-07T00:00:00+00:00"
        with monkeypatch.context() as clock:
            clock.setattr(ex, "_hermes_now", lambda: datetime.fromisoformat("2026-11-07T10:00:00+08:00"))
            later = ex.create_execution("ordered", source="test", scheduled_instant=instant)
            ex.mark_execution_running(later["id"])
            ex.finish_execution(later["id"], success=True)
            clock.setattr(ex, "_hermes_now", lambda: datetime.fromisoformat("2026-11-07T11:00:00+10:00"))
            earlier = ex.create_execution("ordered", source="test")
        assert [row["id"] for row in ex.list_executions(job_id="ordered")] == [later["id"], earlier["id"]]
        assert ex.list_executions(job_id="ordered", before_claimed_at=later["claimed_at"])[0]["id"] == earlier["id"]
        assert completed_occurrence({"id": "ordered"}, instant)
        settings, _scope = resolve_db_configuration()
        pool = get_engine(settings.postgresql)
        def disconnect(connection, record, proxy):
            connection.close()
        event.listen(pool, "checkout", disconnect, once=True)
        with pytest.raises(StorageError):
            ex.get_execution(later["id"])
        assert ex.get_execution(later["id"])["status"] == "completed"
        assert pool.pool.checkedout() == 0


def test_dead_owner_recovery_receipt_and_concurrent_incident_dedup(cron_profiles):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    import subprocess
    import sys
    from cron import executions as ex, incidents as inc
    code = r'''
import sys, sqlite3, json
def reject(*args, **kwargs):
    raise AssertionError('SQLite in PG Cron owner')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from cron import executions as ex
print(json.dumps(ex.create_execution('orphan', source='external')))
'''
    with cron_profiles("one") as home:
        result = subprocess.run([sys.executable, "-c", code, str(home)], capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stderr
        orphan = json.loads(result.stdout)
        assert ex.recover_interrupted_executions() == 1
        assert ex.get_execution(orphan["id"])["status"] == "unknown"
        assert ex.recover_receipted_execution(orphan["id"], "orphan", success=True)["status"] == "completed"
        assert ex.recover_receipted_execution(orphan["id"], "orphan", success=False) is None
        claimed = ex.create_execution("given-up", source="builtin")
        assert ex.give_up_execution(claimed["id"], reason="owner gave up")
        assert ex.recover_receipted_execution(claimed["id"], "given-up", success=True)["status"] == "completed"
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = [future.result() for future in [workers.submit(copy_context().run, inc.upsert_incident,
                       "same", f"provider timeout {index}s") for index in range(8)]]
        assert len({incident for incident, _new in results}) == 1
        assert sum(new for _incident, new in results) == 1
        assert inc.count_incidents("detected") == 1
        assert len(inc.list_incidents()) == 1


def test_scheduler_profile_scope_and_legacy_path_override(cron_profiles, tmp_path, monkeypatch):
    from cron import executions as ex, incidents as inc
    from cron.scheduler_provider import _profile_cron_scope

    with cron_profiles("one") as first:
        pass
    with cron_profiles("two") as second:
        pass
    legacy = tmp_path / "not-a-profile" / "cron" / "executions.db"
    monkeypatch.setattr(ex, "EXECUTIONS_FILE", legacy)
    monkeypatch.setattr(inc, "EXECUTIONS_FILE", legacy)
    with _profile_cron_scope(first):
        attempt = ex.create_execution("same", source="scheduler")
        incident, _new = inc.upsert_incident("same", "failure")
    with _profile_cron_scope(second):
        assert ex.get_execution(attempt["id"]) is None
        assert inc.get_incident(incident) is None
        assert inc.count_incidents() == 0
    with _profile_cron_scope(first):
        assert ex.get_execution(attempt["id"])["job_id"] == "same"
        assert inc.get_incident(incident)["state"] == "detected"
    assert not legacy.exists()
