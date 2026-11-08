"""File snapshots explicitly exclude PG session data and keep the quick CLI entry wired."""

import json
from types import SimpleNamespace

import pytest


def test_quick_backup_cli_records_external_database_exclusion(tmp_path, monkeypatch, capsys):
    from hermes_cli import backup, main
    from hermes_cli.config import atomic_config_write
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(backup, "get_hermes_home", lambda: tmp_path)
    atomic_config_write(tmp_path / "config.yaml", {"storage": {"backend": "postgresql"}})
    main.cmd_backup(SimpleNamespace(quick=True, label="pg-files"))
    snapshot = next((tmp_path / "state-snapshots").glob("*/manifest.json"))
    manifest = json.loads(snapshot.read_text(encoding="utf-8"))
    assert manifest["session_storage"] == {"backend": "postgresql", "included": False}
    assert "excluded" in capsys.readouterr().out and not (tmp_path / "state.db").exists()


def test_session_backend_config_failure_is_a_storage_error_not_daemon_exit(tmp_path, monkeypatch):
    from hermes_cli import config_effective, db_setup
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_db.errors import StorageConfigurationError

    def unavailable(*args, **kwargs):
        raise ConfigBackendUnavailable("injected unavailable config")

    monkeypatch.setattr(config_effective, "load_user_config_effective", unavailable)
    with pytest.raises(StorageConfigurationError, match="configuration is unavailable"):
        db_setup.storage_backend(tmp_path)


def test_pg_root_file_backup_preserves_sqlite_child_owned_shared_room_database(tmp_path):
    from contextlib import closing
    import sqlite3
    import zipfile
    from hermes_cli.backup import _write_full_zip_backup, _import_members
    from hermes_cli.config import atomic_config_write
    root = tmp_path / "home"
    child = root / "profiles" / "native"
    child.mkdir(parents=True)
    atomic_config_write(root / "config.yaml", {"storage": {"backend": "postgresql"}})
    atomic_config_write(child / "config.yaml", {"storage": {"backend": "sqlite"}})
    shared = root / "shared-state.db"
    with closing(sqlite3.connect(shared)) as connection:
        connection.execute("CREATE TABLE proof(value)")
        connection.execute("INSERT INTO proof VALUES ('native child room state')")
        connection.commit()
    (root / "state.db").write_bytes(b"inactive PG root legacy file")
    archive = tmp_path / "mixed.zip"
    assert _write_full_zip_backup(archive, root) == archive
    with zipfile.ZipFile(archive) as zipped:
        assert "shared-state.db" in zipped.namelist() and "state.db" not in zipped.namelist()
        with closing(sqlite3.connect(shared)) as connection:
            connection.execute("DELETE FROM proof")
            connection.commit()
        assert _import_members(zipped, zipped.namelist(), "", root, len(zipped.namelist()))[0] > 0
    with closing(sqlite3.connect(shared)) as connection:
        assert connection.execute("SELECT value FROM proof").fetchall() == [("native child room state",)]
    assert (root / "state.db").read_bytes() == b"inactive PG root legacy file"
