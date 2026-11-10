"""Actual dependency-free SQLite payload selects and restores its own dataset."""

import json
from pathlib import Path

import pytest

from tests.hermes_db.dataset_selection_support import payload_process


def test_pure_sqlite_payload_persists_in_a_new_process(request, tmp_path, record_property):
    from hermes_cli.config import atomic_config_write

    home = tmp_path / "profile"
    home.mkdir()
    atomic_config_write(home / "config.yaml", {"storage": {"backend": "sqlite"}})
    first = payload_process(request, home, "sqlite", "write", "sqlite-marker")
    reopened = payload_process(request, home, "sqlite", "read")
    record_property("processes", json.dumps([first, reopened], sort_keys=True))
    assert first["pid"] != reopened["pid"]
    assert first["visible"] == reopened["visible"] == ["sqlite-marker"]
    assert reopened["history"] == {"sqlite-marker": "sqlite durable history"}
    assert first["sqlite_attempts"] > 0 and reopened["sqlite_attempts"] > 0
    assert not any(first["optional_dependencies"].values())


@pytest.mark.parametrize("storage", [{"backend": "unimplemented"}, {"backend": "postgresql"}])
def test_invalid_selection_is_refused_before_sqlite_opens(request, tmp_path, storage, record_property):
    from hermes_cli.config import atomic_config_write

    home = tmp_path / "profile"
    home.mkdir()
    atomic_config_write(home / "config.yaml", {"storage": storage})
    # This case intentionally uses the dependency-free child while selecting PG/invalid config.
    report = payload_process(request, home, "postgresql", "read", python_backend="sqlite")
    record_property("processes", json.dumps([report], sort_keys=True))
    assert report["error_type"] == "StorageConfigurationError"
    assert report["sqlite_attempts"] == 0
    assert not any(Path(home).glob("*.db*"))
