"""A PG store has no local database file; unknown references preserve archives."""

from contextlib import contextmanager
import os

import pytest


def _configured(monkeypatch, store):
    from hermes_cli import db_setup
    from hermes_db.settings import DatabaseSettings, PostgresSettings
    settings = DatabaseSettings("postgresql", PostgresSettings("postgresql://private:secret@unused/db", "owned"))

    def resolve(home):
        assert home.resolve() == store.scope.profile_home
        return settings, store.scope

    monkeypatch.setattr(db_setup, "resolve_db_configuration", resolve)
    monkeypatch.setattr(db_setup, "storage_backend", lambda home: "postgresql")


def test_core_storage_identity_and_health_do_not_require_a_local_database_file(core_pair):
    from hermes_db.health import profile_home_for_store
    store = core_pair[0]
    store.create_session("s", "cli")
    assert profile_home_for_store(store) == store.scope.profile_home
    assert store.storage_health() == {"backend": "postgresql", "status": "ok"}
    assert not (store.scope.profile_home / "state.db").exists()


def test_pg_readiness_reports_unreachable_storage_instead_of_uninitialized_file(core_pair, monkeypatch):
    from gateway.readiness import _probe_state_db
    from hermes_db.infra.backends.postgresql import engine
    from hermes_db.errors import StorageUnavailableError
    store = core_pair[0]
    _configured(monkeypatch, store)

    class Unreachable:
        def connect(self):
            raise StorageUnavailableError("postgresql://private:secret@unused/db")

    monkeypatch.setattr(engine, "get_engine", lambda settings: Unreachable())
    result = _probe_state_db(store.scope.profile_home)
    assert result["status"] == "degraded"
    assert "private" not in str(result) and "secret" not in str(result)
    assert not (store.scope.profile_home / "state.db").exists()


def test_core_spillover_sweep_preserves_referenced_files_and_uses_explicit_owner(core_pair, monkeypatch):
    from hermes_db.integration import archive_refs
    from tools import tool_result_storage as tools
    owner, other = core_pair
    _configured(monkeypatch, owner)
    folder = owner.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    files = [folder / name for name in ("held.txt", "wire.txt", "orphan.txt")]
    for path in files:
        path.write_text("retained tool output", encoding="utf-8")
        os.utime(path, (0, 0))
    owner.create_session("s", "cli")
    owner.append_message("s", "tool", f"body\x00 after sentinel {files[0]}")
    owner.append_message("s", "assistant", "wire", api_content=f"wire points at {files[1]}")

    @contextmanager
    def read_scope(settings, scope):
        assert scope == owner.scope
        with owner._read() as conn:
            yield conn

    @contextmanager
    def write_scope(settings, scope):
        assert scope == owner.scope
        with owner._write() as conn:
            yield conn

    monkeypatch.setattr(archive_refs, "_read_scope", read_scope)
    monkeypatch.setattr(archive_refs, "_write_scope", write_scope)
    monkeypatch.setattr(tools, "get_spillover_dir", lambda: folder)
    with other._profile.activate():
        assert tools.referenced_spillover_names(folder) == {"held.txt", "wire.txt"}
        assert tools.cleanup_spillover_cache(max_age_hours=1) == 1
    assert files[0].exists() and files[1].exists() and not files[2].exists()


def test_core_unknown_archive_references_keep_every_file(core_pair, monkeypatch):
    from hermes_db.integration import archive_refs
    from hermes_db.errors import StorageUnavailableError
    from tools import tool_result_storage as tools
    owner = core_pair[0]
    _configured(monkeypatch, owner)
    folder = owner.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / "unknown.txt"
    path.write_text("held until the database can answer", encoding="utf-8")
    os.utime(path, (0, 0))

    @contextmanager
    def unavailable(*args):
        raise StorageUnavailableError("injected failure")
        yield

    monkeypatch.setattr(archive_refs, "_read_scope", unavailable)
    monkeypatch.setattr(archive_refs, "_write_scope", unavailable)
    monkeypatch.setattr(tools, "get_spillover_dir", lambda: folder)
    assert tools.referenced_spillover_names(folder) is None
    assert tools.cleanup_spillover_cache(max_age_hours=1) == 0 and path.exists()


def test_core_age_sweep_rechecks_mtime_after_acquiring_the_reference_fence(core_pair, monkeypatch):
    from hermes_db.integration import archive_refs
    from tools import tool_result_storage as tools
    store = core_pair[0]
    _configured(monkeypatch, store)
    folder = store.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / "replaced.txt"
    path.write_text("expired output", encoding="utf-8")
    os.utime(path, (0, 0))

    @contextmanager
    def write_scope(settings, scope):
        path.write_text("fresh replacement", encoding="utf-8")
        with store._write() as conn:
            yield conn

    monkeypatch.setattr(archive_refs, "_write_scope", write_scope)
    monkeypatch.setattr(tools, "get_spillover_dir", lambda: folder)
    assert tools.cleanup_spillover_cache(max_age_hours=1) == 0
    assert path.read_text(encoding="utf-8") == "fresh replacement"


def test_core_archive_projection_scope_bound_and_inactive_rows(core_pair):
    from sqlalchemy import insert
    from hermes_db.tables.conversations import messages
    first, other = core_pair
    for store in core_pair:
        store.create_session("same", "cli")
    first.append_message("same", "user", "spillover/owned.txt")
    other.append_message("same", "user", "spillover/foreign.txt")
    with first._write() as conn:
        conn.execute(messages.update().where(messages.c.store_id == first.scope.store_id).values(active=0, compacted=0))
    assert first.referenced_spillover_names() == {"owned.txt"}
    with first._write() as conn:
        conn.execute(insert(messages), [{"store_id": first.scope.store_id, "id": index + 1000, "session_id": "same",
            "role": "user", "timestamp": 0, "spillover_names": ["bounded.txt"]} for index in range(20000)])
    assert first.referenced_spillover_names() is None
    assert other.referenced_spillover_names() == {"foreign.txt"}


def test_profile_roster_preview_is_bounded_and_skips_tool_rows(store):
    from tui_gateway.methods_profiles import _latest_message_preview
    store.create_session("s", "cli")
    store.append_message("s", "user", " " * 1000 + "first answer")
    assert _latest_message_preview(store, "s") == "first answer"
    store.append_message("s", "assistant", "long answer " * 20)
    store.append_message("s", "tool", "private tool body")
    assert _latest_message_preview(store, "s") == ("long answer " * 20).strip()[:80] + "..."
