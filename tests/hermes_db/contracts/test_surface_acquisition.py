"""Ordinary opens select the owning profile without creating PG state.db files."""

from hermes_cli.db_sessions import _build_session_resources

import pytest

from hermes_db.errors import StorageError


def _profile(home, store_id):
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {store_id}\n")
    (home / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/db\n")


@pytest.mark.parametrize("shared", [False, True])
def test_sqlite_default_redirect_retains_the_live_continuation(tmp_path, monkeypatch, shared):
    import hermes_state
    from hermes_cli.db_sessions import acquire_sessions, open_session_store, session_store_exists
    from hermes_db.access import release_session_store

    target = tmp_path / "redirected" / "state.db"
    with hermes_state.SessionDB(target) as seed:
        seed.create_session("original", "tui")
        seed.end_session("original", "compression")
        seed.create_session("continued", "tui", parent_session_id="original")
        seed.append_message("continued", "assistant", "preserved continuation")
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", target)
    assert session_store_exists()
    store = acquire_sessions() if shared else open_session_store(read_only=True)
    try:
        assert store.resolve_resume_session_id("original") == "continued"
        assert store.get_messages_as_conversation("continued")[0]["content"] == "preserved continuation"
    finally:
        release_session_store(store)


def test_ordinary_pg_opens_without_a_local_file_and_retains_scope(native_registry, core_pair, monkeypatch):
    from hermes_cli import db_sessions as factory
    from hermes_cli.db_sessions import acquire_sessions, open_session_store, session_store_exists
    registry, _ = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope, build=_build_session_resources))
    homes = [db.scope.profile_home for db in core_pair]
    for home, sid in zip(homes, ("one", "two")):
        _profile(home, sid)
        assert session_store_exists(home / "state.db")
    first = acquire_sessions(homes[0] / "state.db")
    second = open_session_store(homes[1] / "state.db", read_only=True)
    try:
        for db, title in ((first, "alpha"), (core_pair[1], "beta")):
            db.create_session("same", "cli")
            db.set_session_title("same", title)
        assert first.get_session_title("same") == "alpha"
        assert second.get_session_title("same") == "beta"
        first.close()
        assert second.get_session_title("same") == "beta"
    finally:
        first.close()
        second.close()
    assert all(not (home / "state.db").exists() for home in homes)


def test_pg_factory_refusal_never_opens_sqlite(tmp_path, unavailable_native):
    from hermes_cli.db_sessions import acquire_sessions, open_session_store
    _profile(tmp_path, "blocked")
    for opener in (acquire_sessions, open_session_store):
        with pytest.raises(StorageError):
            opener(tmp_path / "state.db")
    assert not (tmp_path / "state.db").exists()


def test_managed_worker_cannot_open_an_owner_store(tmp_path, monkeypatch):
    from agent import runtime_session_store
    from hermes_cli.db_sessions import acquire_sessions, open_session_store
    monkeypatch.setattr(runtime_session_store, "is_worker_process", lambda: True)
    for opener in (acquire_sessions, open_session_store):
        with pytest.raises(runtime_session_store.WorkerPersistenceError, match="owner_store_access_from_worker"):
            opener(tmp_path / "state.db")
    assert not (tmp_path / "state.db").exists()


@pytest.mark.parametrize("surface", ["launch", "agent_recall", "tui", "acp"])
def test_pg_entry_failure_is_not_a_memory_only_session(tmp_path, monkeypatch, surface, unavailable_native):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    _profile(tmp_path, "unavailable")
    token = set_hermes_home_override(tmp_path)
    def launch():
        from hermes_cli.main_session_storage import read_session_store
        with read_session_store():
            pytest.fail("PG failure must precede the lookup")

    def recall():
        from run_agent import AIAgent
        agent = object.__new__(AIAgent)
        agent._session_db = None
        agent._get_session_db_for_recall()

    def tui():
        from tui_gateway import server
        monkeypatch.setattr(server, "_db", None)
        monkeypatch.setattr(server, "_launch_state_db_path", lambda: tmp_path / "state.db")
        server._get_db()

    from acp_adapter.session import SessionManager
    # -z now uses this same gateway owner; it no longer acquires a client-side SessionDB.
    openers = {'launch': launch, 'agent_recall': recall,
        'tui': tui, 'acp': lambda: SessionManager()._get_db()}
    try:
        with pytest.raises(StorageError):
            openers[surface]()
    finally:
        reset_hermes_home_override(token)
    assert not (tmp_path / "state.db").exists()
