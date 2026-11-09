"""PG consumer status and ownership work with no state.db or SQLite connection."""

from types import SimpleNamespace


def _pg(monkeypatch, store):
    from hermes_cli import db_setup
    monkeypatch.setattr(db_setup, "storage_backend", lambda home=None: "postgresql")
    monkeypatch.setattr(db_setup, "open_profile_sessions", lambda home=None, **kwargs: store)
    monkeypatch.setattr(store, "close", lambda: None)


def test_core_web_and_tui_rosters_read_pg_without_file_and_disable_file_memos(core_pair, monkeypatch):
    from hermes_cli.web_routers import profiles
    from tui_gateway import profile_roster_cache, server
    store = core_pair[0]
    _pg(monkeypatch, store)
    store.create_session("s", "cli")
    store.set_session_title("s", "Current chat")
    store.append_message("s", "user", "latest preview")
    home = store.scope.profile_home
    assert not (home / "state.db").exists()
    assert profiles._read_profile_db("owned", home, [], lambda db: db.session_count()) == 1
    assert profiles._sidebar_store_cache_key(home) is None
    assert profile_roster_cache.store_signature(home) is None
    row = {}
    server._profile_session_fields(row, home)
    assert row["last_session"]["id"] == "s" and row["last_session"]["preview"] == "latest preview"
    store.append_message("s", "assistant", "updated preview")
    server._profile_session_fields(row, home)
    assert row["last_session"]["preview"] == "updated preview"


def test_core_cli_stats_and_physical_maintenance_have_explicit_backend_boundaries(core_pair, capsys):
    from hermes_cli import sessions_cmd
    store = core_pair[0]
    store.create_session("s", "cli")
    args = SimpleNamespace()
    sessions_cmd._cmd_stats(store, args)
    assert "PostgreSQL" in capsys.readouterr().out
    for handler in (sessions_cmd._cmd_optimize, sessions_cmd._cmd_optimize_storage, sessions_cmd._cmd_clean_markers):
        assert handler(store, args) == 1
        assert "operator-managed" in capsys.readouterr().out


def test_core_profile_repair_scan_and_move_batch_work_without_database_files(core_pair, monkeypatch):
    from hermes_cli import db_setup
    from hermes_cli.sessions_repair_profiles import Store, _MoveBatch, _Session
    source, target = core_pair
    homes = {db.scope.profile_home: db for db in core_pair}
    monkeypatch.setattr(db_setup, "storage_backend", lambda home: "postgresql")
    monkeypatch.setattr(db_setup, "open_profile_sessions", lambda home, **kwargs: homes[home])
    for db in core_pair:
        monkeypatch.setattr(db, "close", lambda: None)
    source.create_session("s", "cli", session_key="agent:target:cli:chat")
    source.append_message("s", "user", "current data")
    first, second = Store("source", source.scope.profile_home), Store("target", target.scope.profile_home)
    session = _Session(read_only=True)
    try:
        assert session.db(first).find_crossed_profile_sessions("source")["foreign"][0]["id"] == "s"
        batch = _MoveBatch(first, second)
        fix = batch.fix_for("s")
        assert fix(session) == {"imported": 1, "moved": 1}
        assert source.get_session("s") is None and target.get_messages("s")[0]["content"] == "current data"
    finally:
        session.close()


def test_session_resource_releases_only_its_handle_once(core_pair):
    from hermes_db.handle import DatabaseHandle
    from hermes_db.core.session_resource import SessionResource
    store = core_pair[0]
    releases = []
    handle = DatabaseHandle(store.scope, store, "runtime", lambda: releases.append(True))
    with SessionResource(handle) as resource:
        assert resource.scope == store.scope and resource.runtime == "runtime"
        resource.create_session("s", "cli")
    resource.close()
    assert releases == [True] and store.get_session("s") is not None


def test_pg_doctor_and_file_backup_report_external_storage_without_sqlite_fix(core_pair, monkeypatch, capsys):
    from hermes_cli import backup_storage, doctor, doctor_state
    from hermes_db import health
    store = core_pair[0]
    _pg(monkeypatch, store)
    monkeypatch.setattr(doctor, "HERMES_HOME", store.scope.profile_home)
    monkeypatch.setattr(health, "configured_probe", lambda home: {"backend": "postgresql", "status": "ok"})
    assert doctor_state._check_state_db(True).fixed == 0
    assert "PostgreSQL" in capsys.readouterr().out
    assert backup_storage.snapshot_storage(store.scope.profile_home) == {"backend": "postgresql", "included": False}
    assert "excluded" in capsys.readouterr().out
    monkeypatch.setattr(health, "configured_probe", lambda home: {"status": "degraded"})
    result = doctor_state._check_state_db(True)
    assert result.manual_issues and not result.fixed
    assert not (store.scope.profile_home / "state.db").exists()


def test_pg_analytics_unavailable_returns_storage_status_without_file_repair_hint(tmp_path):
    import pytest
    from fastapi import HTTPException
    from hermes_cli.web_routers._common import corrupt_store_as_status
    from hermes_db.errors import StorageUnavailableError
    with pytest.raises(HTTPException) as result:
        with corrupt_store_as_status(tmp_path / "state.db"):
            raise StorageUnavailableError("backend unavailable")
    assert result.value.status_code == 503
    assert result.value.detail["error"] == "session_storage_unavailable"
    assert "repair" not in result.value.detail["message"]
