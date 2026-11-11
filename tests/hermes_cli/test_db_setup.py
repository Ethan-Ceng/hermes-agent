"""Load actual profile configs and secrets without a database or global env swaps."""

import pytest

from hermes_cli.db_session_schema import initialize_new_profile_sessions
from hermes_cli.db_setup import open_profile_db, resolve_db_configuration
from hermes_db.errors import StorageConfigurationError, StorageUnavailableError


def _profile(tmp_path, name, store="store-a", secret="a-secret"):
    home = tmp_path / name
    home.mkdir()
    (home / "config.yaml").write_text(
        "storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {store}\n    pool_size: 2\n"
        "    max_overflow: 1\n    connection_budget: 3\n", encoding="utf-8")
    (home / ".env").write_text(f"HERMES_POSTGRES_DSN=postgresql://user:{secret}@localhost/db\n", encoding="utf-8")
    return home


def test_effective_profile_config_and_secrets_are_isolated(tmp_path, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    from hermes_constants import get_hermes_home

    first = _profile(tmp_path, "one")
    second = _profile(tmp_path, "two", store="store-b", secret="b-secret")
    monkeypatch.setenv("HERMES_POSTGRES_DSN", "postgresql://user:launch-secret@localhost/db")
    before = get_hermes_home()
    token = set_secret_scope({"HERMES_POSTGRES_DSN": "postgresql://u:pinned-secret@localhost/db"},
                             profile_home=str(first))
    try:
        a, sa = resolve_db_configuration(first)
        b, sb = resolve_db_configuration(second)
        assert "pinned-secret" in a.postgresql.dsn
        assert "b-secret" in b.postgresql.dsn
        assert (sa.store_id, sb.store_id) == ("store-a", "store-b")
        assert a.postgresql.pool_size == 2
        assert b.postgresql.connection_budget == 3
        assert "b-secret" not in repr(b)
        assert get_hermes_home() == before
    finally:
        reset_secret_scope(token)


def test_missing_profile_secret_does_not_use_another_profiles_process_env(tmp_path, monkeypatch):
    from agent.secret_scope import set_multiplex_context, reset_multiplex_context

    home = _profile(tmp_path, "named")
    (home / ".env").write_text("", encoding="utf-8")
    monkeypatch.setenv("HERMES_POSTGRES_DSN", "postgresql://user:launch-secret@localhost/db")
    token = set_multiplex_context(True)
    try:
        with pytest.raises(StorageConfigurationError, match="secret is missing"):
            resolve_db_configuration(home)
    finally:
        reset_multiplex_context(token)


def test_default_sqlite_entry_consumes_config_and_owns_its_home(tmp_path):
    home = tmp_path / "sqlite"
    home.mkdir()
    (home / "config.yaml").write_text("storage: {backend: sqlite}\n", encoding="utf-8")
    initialize_new_profile_sessions(home)
    with open_profile_db(home) as db:
        assert db.scope.profile_home == home.resolve()
        db.sessions.create_session("s", source="cli")
    assert (home / "state.db").is_file()


def test_deferred_sqlite_reads_remain_bound_to_the_owning_profile(tmp_path):
    from hermes_state import SessionResumeTooLargeError
    from hermes_constants import get_hermes_home

    home = tmp_path / "small-resume"
    home.mkdir()
    (home / "config.yaml").write_text("sessions: {max_resume_messages: 1}\n", encoding="utf-8")
    caller_home = get_hermes_home()
    initialize_new_profile_sessions(home)
    with open_profile_db(home) as db:
        db.sessions.create_session("s", source="cli")
        db.sessions.append_message("s", role="user", content="one")
        db.sessions.append_message("s", role="assistant", content="two")
        with pytest.raises(SessionResumeTooLargeError):
            db.sessions.assert_resume_safe("s")
    assert get_hermes_home() == caller_home


def test_postgres_entry_is_fail_closed_when_unavailable(tmp_path, monkeypatch):
    pytest.importorskip("psycopg", reason="optional postgresql extra")
    home = _profile(tmp_path, "pg")
    def unavailable(settings, scope):
        raise StorageUnavailableError('test storage unavailable')
    monkeypatch.setattr("hermes_cli.db_sessions._construct_store", unavailable)
    with pytest.raises(StorageUnavailableError):
        open_profile_db(home)
    assert not (home / "state.db").exists()


@pytest.mark.parametrize("config", [
    "storage: []", "storage: {session: []}", "storage: {backend: unknown}",
    "storage: {backend: postgresql, postgresql: {schema: hermes}}",
])
def test_invalid_config_is_an_error_not_sqlite_fallback(tmp_path, config):
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    with pytest.raises(StorageConfigurationError):
        resolve_db_configuration(tmp_path)
    assert not (tmp_path / "state.db").exists()


def test_dsn_secret_routes_through_config_registry():
    from hermes_cli.config import _validate_config_key
    from hermes_cli.config_defaults import OPTIONAL_ENV_VARS
    from hermes_cli.config_env_routing import is_env_setting_key

    assert _validate_config_key("storage.postgresql.connection_budget")[0]
    assert is_env_setting_key("HERMES_POSTGRES_DSN")
    assert OPTIONAL_ENV_VARS["HERMES_POSTGRES_DSN"]["password"]
