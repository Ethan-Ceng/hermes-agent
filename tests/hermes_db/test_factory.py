"""Backend selection and explicit resource ownership at the factory boundary."""

import builtins

import pytest

from hermes_db.errors import StorageClosedError, StorageDriverError, StorageSchemaError
from hermes_cli.db_sessions import acquire_db
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings, PostgresSettings


def test_sqlite_handles_share_registry_and_release_independently(tmp_path):
    from hermes_state import SessionDB
    with SessionDB(db_path=tmp_path / "state.db"):
        pass
    settings, scope = DatabaseSettings(), DatabaseScope(tmp_path)
    first, second = acquire_db(settings, scope), acquire_db(settings, scope)
    try:
        from hermes_db.domains.runtime.access import runtime_for_store
        assert runtime_for_store(first.sessions) is first.runtime
        first.sessions.create_session("s", source="cli")
        epoch = first.runtime.begin_epoch(instance_id="owner")
        admitted = first.runtime.admit_input(epoch=epoch, principal_id="p", session_id="s",
                                              request_id="r", payload={"input": "hi"})
        assert second.runtime.get_admission(admission_id=admitted["admission_id"]) == admitted
        first.close()
        first.close()
        with pytest.raises(StorageClosedError):
            _ = first.sessions
        assert second.sessions.get_session("s")["id"] == "s"
    finally:
        first.close()
        second.close()
    with acquire_db(settings, scope) as reopened:
        assert reopened.sessions.get_session("s")["id"] == "s"


def test_postgres_uninitialized_backend_never_opens_sqlite(tmp_path, monkeypatch):
    pytest.importorskip("psycopg", reason="optional postgresql extra")
    settings = DatabaseSettings("postgresql", PostgresSettings("postgresql://localhost/unused", "hermes"))
    def uninitialized(settings, scope):
        raise StorageSchemaError('schema is not initialized')
    monkeypatch.setattr("hermes_cli.db_sessions._construct_store", uninitialized)
    with pytest.raises(StorageSchemaError):
        acquire_db(settings, DatabaseScope(tmp_path, "stable"))
    assert not (tmp_path / "state.db").exists()


def test_missing_driver_reports_pm_action_without_credentials(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def no_psycopg(name, *args, **kwargs):
        if name == "psycopg":
            raise ModuleNotFoundError("private driver error")
        return original_import(name, *args, **kwargs)

    settings = DatabaseSettings("postgresql", PostgresSettings("postgresql://u:secret@host/db", "hermes"))
    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    with pytest.raises(StorageDriverError, match="Hermes PM") as error:
        acquire_db(settings, DatabaseScope(tmp_path, "stable"))
    assert "secret" not in str(error.value)
    assert not (tmp_path / "state.db").exists()
