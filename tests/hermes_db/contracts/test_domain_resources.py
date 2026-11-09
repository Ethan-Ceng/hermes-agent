"""Ownership, capability errors and lazy imports at the domain boundary."""

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest

from hermes_cli.config import atomic_config_write
from hermes_db.errors import StorageClosedError, StorageConfigurationError, StorageNotReadyError
from hermes_db.factory import acquire_domain, acquire_profile_domain
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


def test_sqlite_path_is_only_a_domain_location_not_a_profile(tmp_path, monkeypatch):
    from hermes_db.core.catalog import POSTGRES_DOMAINS
    monkeypatch.delitem(POSTGRES_DOMAINS, "sessions")
    owner = tmp_path / "owner"
    owner.mkdir()
    atomic_config_write(owner / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": {
        "schema": "hermes", "store_id": "owner-store"}}})
    (owner / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/test\n")
    for nested in (owner / "cron/notepad.db", owner / "boards/work/kanban.db"):
        with pytest.raises(StorageNotReadyError, match="sessions.*not implemented"):
            acquire_profile_domain("sessions", profile_home=owner, sqlite_path=nested)
        assert not nested.exists()
    with pytest.raises(StorageConfigurationError, match="Unknown storage domain"):
        acquire_profile_domain("typo", profile_home=owner)


def test_resource_scope_survives_thread_context_and_close_is_local(tmp_path):
    first = acquire_domain("projects", DatabaseSettings(), DatabaseScope(tmp_path / "one"),
                           sqlite_path=tmp_path / "one/projects.db")
    second = acquire_domain("projects", DatabaseSettings(), DatabaseScope(tmp_path / "two"))
    with ThreadPoolExecutor(max_workers=1) as workers:
        assert workers.submit(lambda: first.scope.profile_home).result() == (tmp_path / "one").resolve()
    first.close()
    first.close()
    with pytest.raises(StorageClosedError), first:
        pytest.fail("closed resource must not be reusable")
    with second:
        assert second.scope.profile_home == (tmp_path / "two").resolve()
        with pytest.raises(StorageNotReadyError, match="native implementation"), second.read():
            pytest.fail("a domain resource must not pretend to translate SQLite SQL")


def test_domain_protocol_and_sqlite_resource_without_pg_dependencies(tmp_path):
    code = r'''
import importlib.abc
import sys
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic'}:
            raise ImportError('optional PG dependency unavailable')
sys.meta_path.insert(0, BlockDrivers())
from hermes_db.core.catalog import KNOWN_DOMAINS
from hermes_db.factory import acquire_profile_domain
with acquire_profile_domain('projects', profile_home=sys.argv[1]) as resource:
    assert resource.settings.backend == 'sqlite'
    assert resource.name in KNOWN_DOMAINS
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_worker_cannot_acquire_owner_domain(tmp_path, monkeypatch):
    from agent import runtime_session_store

    monkeypatch.setattr(runtime_session_store, "is_worker_process", lambda: True)
    with pytest.raises(runtime_session_store.WorkerPersistenceError, match="owner_store_access_from_worker"):
        acquire_domain("projects", DatabaseSettings(), DatabaseScope(tmp_path))


def _try_inherited_resource(resource, channel):
    try:
        with resource:
            channel.send("incorrectly accepted")
    except StorageClosedError:
        channel.send("refused")
    finally:
        channel.close()


@pytest.mark.platforms("posix")
def test_forked_child_must_acquire_its_own_resource(tmp_path):
    import multiprocessing

    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    with acquire_domain("projects", DatabaseSettings(), DatabaseScope(tmp_path)) as resource:
        process = context.Process(target=_try_inherited_resource, args=(resource, child))
        process.start()
        child.close()
        try:
            assert parent.poll(10)
            assert parent.recv() == "refused"
            process.join(10)
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)
            parent.close()
