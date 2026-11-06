"""File snapshots explicitly exclude PG session data and keep the quick CLI entry wired."""

import json
from types import SimpleNamespace

import pytest


def test_quick_backup_cli_records_external_database_exclusion(tmp_path, monkeypatch, capsys):
    from hermes_cli import backup, main
    from hermes_cli.config import atomic_config_write
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(backup, "get_hermes_home", lambda: tmp_path)
    atomic_config_write(tmp_path / "config.yaml", {"storage": {"session": {"backend": "postgresql"}}})
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
        db_setup.session_backend(tmp_path)
