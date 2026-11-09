"""Actual passive evidence entrypoints with every SQLite connection rejected."""

from contextlib import contextmanager
from dataclasses import replace
import sqlite3

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def evidence_profiles(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
    from agent import verification_evidence as ve
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_cli.config import atomic_config_write
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.schema import upgrade_schema

    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")

    @contextmanager
    def owner(name):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": {
            "schema": pg.schema, "store_id": name, "pool_size": pg.pool_size,
            "max_overflow": pg.max_overflow, "connection_budget": pg.connection_budget}}})
        token = set_hermes_home_override(home)
        secret = set_secret_scope({"HERMES_POSTGRES_DSN": pg.dsn}, profile_home=str(home))
        try:
            yield ve, workspace, home
        finally:
            reset_secret_scope(secret)
            reset_hermes_home_override(token)

    def reject(*args, **kwargs):
        pytest.fail("PG evidence must reject all SQLite connections, including memory and URI")
    monkeypatch.setattr(sqlite3, "connect", reject)
    return owner, pg


def test_actual_record_edit_status_reopen_and_profile_isolation(evidence_profiles, request):
    owner, _pg = evidence_profiles
    with owner("one") as (ve, workspace, home):
        event = ve.record_terminal_result(command="python -m pytest", cwd=workspace, session_id="same",
                                           exit_code=0, output="中文\x00🙂 passed")
        assert event["status"] == "passed"
        assert ve.verification_status(session_id="same", cwd=workspace)["evidence"]["output_summary"] == "中文\x00🙂 passed"
        ve.mark_workspace_edited(session_id="same", cwd=workspace, paths=["a.py"])
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "stale"
        ve.record_verify_run(root=workspace, session_id="other", ok=True, scope="targeted")
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "stale"
        ve.record_verify_run(root=workspace, session_id="other", ok=True)
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "passed"
        assert not (home / "verification_evidence.db").exists()
    with owner("two") as (ve, workspace, _home):
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "unverified"
        ve.record_verify_run(root=workspace, session_id="same", ok=False)
    from hermes_db.backends.postgresql.engine import close_engines
    close_engines()
    with owner("one") as (ve, workspace, _home):
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "passed"
        import subprocess
        import sys
        code = r'''
import sys, sqlite3
def reject(*args, **kwargs):
    raise AssertionError('SQLite connection in PG child process')
sqlite3.connect = reject
from tests.hermes_db.pg_support import read_test_config
from agent.secret_scope import set_secret_scope
from hermes_constants import set_hermes_home_override
config = read_test_config(sys.argv[1])
set_hermes_home_override(sys.argv[2])
set_secret_scope({'HERMES_POSTGRES_DSN': config.settings.dsn}, profile_home=sys.argv[2])
from agent import verification_evidence as ve
assert ve.verification_status(session_id='same', cwd=sys.argv[3])['status'] == 'passed'
ve.mark_workspace_edited(session_id='same', cwd=sys.argv[3], paths=['child.py'])
'''
        result = subprocess.run([sys.executable, "-c", code, request.config.getoption("--postgres-test-config"),
                                 str(_home), str(workspace)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert ve.verification_status(session_id="same", cwd=workspace)["status"] == "stale"


def test_concurrent_edits_merge_and_retention_preserves_references(evidence_profiles, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from sqlalchemy import func, select
    from hermes_db.domains.verification import postgres_resource
    from hermes_db.tables.verification import verification_events as events

    owner, _pg = evidence_profiles
    with owner("one") as (ve, workspace, _home):
        with ThreadPoolExecutor(max_workers=4) as workers:
            futures = [workers.submit(copy_context().run, ve.mark_workspace_edited, session_id="editor\x00🙂",
                                      cwd=workspace, paths=[f"{index}.py"]) for index in range(12)]
            for future in futures:
                future.result()
        state = ve.verification_status(session_id="editor\x00🙂", cwd=workspace)
        assert set(state["changed_paths"]) == {f"{index}.py" for index in range(12)}
        monkeypatch.setattr(ve, "_MAX_EVENTS_PER_SESSION_ROOT", 3)
        monkeypatch.setattr(ve, "_MAX_TOTAL_UNREFERENCED_EVENTS", 4)
        proof = ve.record_verify_run(root=workspace, session_id="verifier", ok=True)
        for _ in range(6):
            ve.record_verify_run(root=workspace, session_id="verifier", ok=False, scope="targeted")
        state = ve.verification_status(session_id="editor\x00🙂", cwd=workspace)
        assert state["status"] == "passed"
        assert state["evidence"]["id"] == proof["id"]
        with postgres_resource() as resource, resource.read() as conn:
            assert conn.scalar(select(func.count()).select_from(events).where(events.c.store_id == "one")) == 4
        with monkeypatch.context() as clock:
            clock.setattr(ve, "_utc_now", lambda: "2020-01-01T00:00:00+00:00")
            ve.mark_workspace_edited(session_id="expired", cwd=workspace, paths=["old.py"])
        ve.record_verify_run(root=workspace, session_id="verifier", ok=False)
        assert ve.verification_status(session_id="expired", cwd=workspace)["changed_paths"] == []


def test_terminal_stop_edit_consumers_and_failure_is_explicit(evidence_profiles, caplog):
    from sqlalchemy import text
    from agent.verification_stop import _verification_snapshot
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageSchemaError
    from tools.file_tools_read_tracking import _mark_verification_stale
    from tools.terminal_tool_result import _verification_evidence

    owner, pg = evidence_profiles
    with owner("one") as (ve, workspace, _home):
        changed = workspace / "changed.py"
        changed.write_text("value = 1\n")
        result = _verification_evidence("python -m pytest", str(workspace), "one", 0, "passed")
        assert result["status"] == "passed"
        _mark_verification_stale("turn", [str(changed)], session_id="one")
        snapshot = _verification_snapshot(session_id="one", changed_paths=[str(changed)])
        assert snapshot[0]["status"] == "stale"
        with get_engine(pg).begin() as conn:
            quoted = conn.dialect.identifier_preparer.quote(pg.schema)
            conn.execute(text(f"DROP TABLE {quoted}.verification_locks"))
        result = _verification_evidence("python -m pytest", str(workspace), "one", 0, "passed")
        assert result["status"] == "unavailable"
        assert "verification" in result["error"]
        _mark_verification_stale("turn", [str(changed)], session_id="one")
        assert "could not record the edit" in caplog.text
        with pytest.raises(StorageSchemaError):
            ve.verification_status(session_id="one", cwd=workspace)
