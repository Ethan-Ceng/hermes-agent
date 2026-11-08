"""PG file backups exclude every owned database and preserve file content without SQLite."""

import json
from types import SimpleNamespace
import zipfile
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

LEGACY = ("state.db", "shared-state.db", "projects.db", "verification_evidence.db", "retaindb_queue.db",
    "cron/executions.db", "cron/deliveries.db", "cron/notepad.db", "kanban/boards/old/kanban.db",
    "platforms/matrix/store/crypto.db", "telemetry/shared_metrics/metrics.sqlite3", "plugin-data/old/portable.db")


def legacy_files(home):
    for relative in LEGACY:
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"preserve inactive SQLite bytes")


def test_pg_quick_snapshot_never_opens_legacy_system_databases(pg_profiles):
    from hermes_cli.backup import create_quick_snapshot
    with pg_profiles("one") as home:
        legacy_files(home)
        identity = create_quick_snapshot(hermes_home=home)
        manifest = json.loads((home / "state-snapshots" / identity / "manifest.json").read_text(encoding="utf-8"))
        assert not set(LEGACY).intersection(manifest["files"])
        assert manifest["database_storage"]["backend"] == "postgresql"
        assert manifest["database_storage"]["included"] is False
        assert (home / "state.db").read_bytes() == b"preserve inactive SQLite bytes"


def test_pg_full_backup_keeps_opaque_user_file_and_declares_external_database(pg_profiles, tmp_path, monkeypatch):
    from hermes_cli.backup import run_backup
    with pg_profiles("one") as home:
        monkeypatch.setenv("HERMES_HOME", str(home))
        legacy_files(home)
        (home / "user-content.db").write_bytes(b"opaque attachment content, not a system database")
        output = tmp_path / "profile-backup.zip"
        assert run_backup(SimpleNamespace(output=str(output), keep=0))
        with zipfile.ZipFile(output) as archive:
            assert not set(LEGACY).intersection(archive.namelist())
            assert archive.read("user-content.db") == b"opaque attachment content, not a system database"
            metadata = json.loads(archive.comment)
            assert metadata["hermes_database_storage"]["profiles"]["."] == "postgresql"
        assert all((home / relative).read_bytes() == b"preserve inactive SQLite bytes" for relative in LEGACY)


def test_selected_preflight_reports_pg_exclusion_without_opening_state_file(pg_profiles):
    from hermes_cli.backup_preflight import preflight
    with pg_profiles("one") as home:
        legacy_files(home)
        result = preflight(home)
        assert result["backend"] == "postgresql" and result["path"] is None
        assert result["database_included"] is False
        assert not list(home.glob("state.db.pre-update-emergency-*"))


def test_pg_quick_restore_recovers_files_without_touching_database(pg_profiles):
    from hermes_cli.backup import create_quick_snapshot, restore_quick_snapshot
    from hermes_cli.db_setup import open_profile_db
    with pg_profiles("one") as home:
        legacy_files(home)
        aliases = home / "channel_aliases.json"
        aliases.write_text('{"alias":"before"}', encoding="utf-8")
        with open_profile_db(home) as handle:
            handle.sessions.create_session("not-file-backed", "cli")
            handle.sessions.append_message("not-file-backed", "user", "database remains authoritative")
        identity = create_quick_snapshot(hermes_home=home)
        aliases.write_text('{"alias":"after"}', encoding="utf-8")
        assert restore_quick_snapshot(identity, hermes_home=home)
        assert json.loads(aliases.read_text(encoding="utf-8")) == {"alias": "before"}
        with open_profile_db(home) as handle:
            assert handle.sessions.get_messages_as_conversation("not-file-backed")[0]["content"] == "database remains authoritative"
        assert (home / "state.db").read_bytes() == b"preserve inactive SQLite bytes"


def test_pg_refuses_old_sqlite_snapshot_before_any_file_changes(pg_profiles):
    from hermes_cli.backup import restore_quick_snapshot
    with pg_profiles("one") as home:
        original = (home / "config.yaml").read_bytes()
        snapshot = home / "state-snapshots" / "old-native"
        snapshot.mkdir(parents=True)
        (snapshot / "state.db").write_bytes(b"old database image")
        (snapshot / "config.yaml").write_text("storage:\n  backend: sqlite\n", encoding="utf-8")
        (snapshot / "manifest.json").write_text(json.dumps({"files": {"state.db": 18, "config.yaml": 27},
            "session_storage": {"backend": "sqlite", "included": True}}), encoding="utf-8")
        assert not restore_quick_snapshot("old-native", hermes_home=home)
        assert (home / "config.yaml").read_bytes() == original
        assert not (home / "state.db").exists()


def test_pg_full_archive_restore_keeps_opaque_db_named_file(pg_profiles, tmp_path, monkeypatch):
    from hermes_cli import backup
    with pg_profiles("one") as home:
        monkeypatch.setenv("HERMES_HOME", str(home))
        user_file = home / "user-content.db"
        user_file.write_bytes(b"opaque user content")
        output = tmp_path / "files-only.zip"
        assert backup.run_backup(SimpleNamespace(output=str(output), keep=0))
        user_file.write_bytes(b"changed")
        revived = []
        # Service bootstrap is outside this storage contract; never restart a real user instance.
        monkeypatch.setattr(backup, "_revive_gateway_after_import", lambda owner: revived.append(owner))
        assert backup.run_import(SimpleNamespace(zipfile=str(output), force=True)) is None
        assert user_file.read_bytes() == b"opaque user content"
        assert revived == [home]


def test_pg_automatic_zip_has_same_database_boundary(pg_profiles, tmp_path):
    from hermes_cli.backup import _write_full_zip_backup
    with pg_profiles("one") as home:
        legacy_files(home)
        archive_path = tmp_path / "automatic.zip"
        assert _write_full_zip_backup(archive_path, home) == archive_path
        with zipfile.ZipFile(archive_path) as archive:
            assert not set(LEGACY).intersection(archive.namelist())
            assert json.loads(archive.comment)["hermes_database_storage"]["profiles"]["."] == "postgresql"


def test_pg_rejects_native_archive_before_overwriting_config(pg_profiles, tmp_path):
    from hermes_cli import backup
    with pg_profiles("one") as home:
        original = (home / "config.yaml").read_bytes()
        archive_path = tmp_path / "legacy.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("config.yaml", "storage:\n  backend: sqlite\n")
            archive.writestr("state.db", "historical image")
        with zipfile.ZipFile(archive_path) as archive, pytest.raises(ValueError, match="PostgreSQL"):
            backup._import_members(archive, archive.namelist(), "", home, len(archive.namelist()))
        assert (home / "config.yaml").read_bytes() == original
        assert not (home / "state.db").exists()


@pytest.mark.parametrize("archive_kind", ["zip", "quick"])
def test_pg_refuses_contradictory_backend_metadata_before_config_changes(pg_profiles, tmp_path, archive_kind):
    from hermes_cli import backup
    with pg_profiles("one") as home:
        original = (home / "config.yaml").read_bytes()
        native_config = b"storage:\n  backend: sqlite\n"
        if archive_kind == "zip":
            output = tmp_path / "contradictory.zip"
            with zipfile.ZipFile(output, "w") as archive:
                archive.comment = json.dumps({"hermes_database_storage": {"version": 1, "profiles": {".": "postgresql"}}}).encode()
                archive.writestr("config.yaml", native_config)
            with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="backend"):
                backup._import_members(archive, archive.namelist(), "", home, 1)
        else:
            snapshot = home / "state-snapshots" / "contradictory"
            snapshot.mkdir(parents=True)
            (snapshot / "config.yaml").write_bytes(native_config)
            (snapshot / "manifest.json").write_text(json.dumps({"files": {"config.yaml": len(native_config)},
                "database_storage": {"backend": "postgresql", "included": False}}), encoding="utf-8")
            assert not backup.restore_quick_snapshot("contradictory", hermes_home=home)
        assert (home / "config.yaml").read_bytes() == original
