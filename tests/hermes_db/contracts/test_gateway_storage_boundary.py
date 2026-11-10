"""The ordinary routing store never imports or writes a file fallback in PG mode."""

import json

import pytest

from hermes_db.errors import StorageUnavailableError


def _routing_store(db, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home = db.scope.profile_home
    home.mkdir(parents=True, exist_ok=True)
    token = set_hermes_home_override(home)
    try:
        monkeypatch.setattr(SessionStore, "_open_session_db_for_active_scope", lambda self, **kw: db)
        store = SessionStore(home / "sessions", GatewayConfig())
        store._db = db
        return store
    finally:
        reset_hermes_home_override(token)


def test_pg_startup_does_not_adopt_a_sqlite_routing_mirror(core_pair, monkeypatch):
    import builtins
    from datetime import datetime
    from gateway.session import SessionEntry
    store = _routing_store(core_pair[0], monkeypatch)
    store.sessions_dir.mkdir(parents=True, exist_ok=True)
    mirror = store.sessions_dir / "sessions.json"
    now = datetime.now()
    mirror.write_text(json.dumps({"old-route": SessionEntry("old-route", "old", now, now).to_dict()}))
    opened = []
    original_open = builtins.open

    def observe(path, *args, **kwargs):
        if path == mirror:
            opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", observe)
    store._ensure_loaded()
    assert opened == []
    assert store._entries == {}
    assert core_pair[0].load_gateway_routing_entries(scope=store._routing_scope()) == {}


def test_failed_pg_routing_save_never_becomes_a_successful_file_save(core_pair, monkeypatch):
    store = _routing_store(core_pair[0], monkeypatch)
    store._write_sessions_json = False

    def unavailable(*args, **kwargs):
        raise StorageUnavailableError("injected PG outage")

    monkeypatch.setattr(core_pair[0], "replace_gateway_routing_entries", unavailable)
    with pytest.raises(StorageUnavailableError):
        store._persist_routing_data({}, 1)
    assert not (store.sessions_dir / "sessions.json").exists()
    assert not getattr(store, "_persisted_routing_generation", 0)


def test_pg_open_failure_and_backoff_both_remain_unavailable(tmp_path, monkeypatch):
    from gateway.session import SessionStore
    from gateway.session_db_recovery import RecoverableHandleCache
    from hermes_cli import db_sessions as access
    home = tmp_path / "pg"
    home.mkdir()
    (home / "config.yaml").write_text("storage: {backend: postgresql}\n")
    store = object.__new__(SessionStore)
    store._db_handle_cache = RecoverableHandleCache()
    attempts = []

    def unavailable(path):
        attempts.append(path)
        raise StorageUnavailableError("injected PG outage")

    monkeypatch.setattr(access, "acquire_sessions", unavailable)
    for _ in range(2):
        with pytest.raises(StorageUnavailableError):
            store._open_session_db_for_active_scope(home / "state.db")
    assert len(attempts) == 1
    assert not (home / "state.db").exists()
