"""Driver preparation failures stay observable before application file creation."""

import pytest

from hermes_db.infra.backends.sqlite import generation, session_connections
from hermes_state import SessionDB, get_last_init_error
from hermes_state_guard import _set_last_init_error


def test_driver_preparation_failure_is_recorded_before_profile_files_exist(tmp_path, monkeypatch):
    path = tmp_path / "uncreated-profile" / "state.db"
    _set_last_init_error("")

    def unavailable_retirement():
        raise RuntimeError("driver retirement capability unavailable")

    monkeypatch.setattr(session_connections, "_close_time_checkpoint_configurable", lambda: False)
    monkeypatch.setattr(generation, "_prepare_connection_retirement", unavailable_retirement)
    with pytest.raises(RuntimeError, match="driver retirement capability unavailable"):
        SessionDB(path)
    assert not path.parent.exists()
    assert "driver retirement capability unavailable" in (get_last_init_error() or "")


def test_identity_header_fallback_retries_transient_driver_io_error(tmp_path, monkeypatch):
    import sqlite3

    db = SessionDB(tmp_path / "state.db")
    resource = db._connections
    writer = resource._conn
    expected = writer.execute("PRAGMA application_id").fetchone()[0]
    attempts = []

    class TransientDriver:
        def execute(self, statement):
            attempts.append(statement)
            if len(attempts) == 1:
                raise sqlite3.OperationalError("disk I/O error")
            return writer.execute(statement)

    monkeypatch.setattr(generation, "_read_sqlite_application_id", lambda path: None)
    resource._db_file_application_id = 0
    resource._conn = TransientDriver()
    try:
        assert resource._record_db_file_identity() is None
        assert len(attempts) == 2
        assert resource._db_file_application_id == expected
    finally:
        resource._conn = writer
        db.close()
