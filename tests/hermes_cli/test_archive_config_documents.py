"""Archive configuration is frozen evidence, not the restoring Profile's effective config."""

import traceback

import pytest

from hermes_cli.backup_database_policy import DatabaseBackupPolicy
from hermes_db.errors import StorageConfigurationError


def make_policy(tmp_path):
    from hermes_cli.config import atomic_config_write
    home = tmp_path / "profile"
    home.mkdir()
    atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql"}})
    return home, DatabaseBackupPolicy(home, {".": "postgresql"})


def test_archive_document_keeps_raw_values_without_consulting_live_config(tmp_path, monkeypatch):
    from hermes_cli import config_backend

    home, policy = make_policy(tmp_path)
    before = (home / "config.yaml").read_bytes()
    payload = b"\xef\xbb\xbfstorage:\n  backend: postgresql\nnote: ${ARCHIVE_NOTE}\n"
    snapshot = tmp_path / "archived.yaml"
    snapshot.write_bytes(payload)
    monkeypatch.setenv("ARCHIVE_NOTE", "must-not-be-expanded")
    monkeypatch.setenv("ARCHIVE_BACKEND", "postgresql")

    def reject_live_backend():
        raise AssertionError("Archive validation must not consult the live configuration backend")

    monkeypatch.setattr(config_backend, "get_config_backend", reject_live_backend)
    parsed = config_backend.parse_config_document(payload)
    assert parsed == config_backend.FileBackend.read_path(snapshot)
    assert parsed == {"storage": {"backend": "postgresql"}, "note": "${ARCHIVE_NOTE}"}
    policy.validate_config("config.yaml", lambda: payload)
    with pytest.raises(StorageConfigurationError, match="storage.backend"):
        policy.validate_config("config.yaml", lambda: b"storage:\n  backend: ${ARCHIVE_BACKEND}\n")
    assert (home / "config.yaml").read_bytes() == before


@pytest.mark.parametrize("payload", [b"", b"[]", b"null", b"storage: [private-archive-token", b"\xff"])
def test_unverifiable_archive_never_uses_defaults_or_exposes_payload(tmp_path, payload):
    home, policy = make_policy(tmp_path)
    before = (home / "config.yaml").read_bytes()
    with pytest.raises(StorageConfigurationError, match="Cannot verify backup") as caught:
        policy.validate_config("config.yaml", lambda: payload)
    assert "private-archive-token" not in "".join(traceback.format_exception(caught.value))
    assert (home / "config.yaml").read_bytes() == before
