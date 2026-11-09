"""Native acquisitions share scoped stores, not connections or caller ownership."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest


def _settings():
    from hermes_db.settings import PostgresSettings
    return PostgresSettings("postgresql://unused/db", "owned")


def test_public_factory_selects_native_and_preserves_borrowers(native_registry, core_pair):
    pytest.importorskip('psycopg')
    from hermes_db.factory import acquire_db
    from hermes_db.settings import DatabaseSettings
    from hermes_db.errors import StorageClosedError
    scope = core_pair[0].scope
    settings = DatabaseSettings('postgresql', _settings())
    first = acquire_db(settings, scope)
    second = acquire_db(settings, scope)
    try:
        first.sessions.create_session('native-factory', 'cli')
        assert first.sessions is second.sessions
        first.close()
        assert second.sessions.get_session('native-factory')['source'] == 'cli'
        with pytest.raises(StorageClosedError):
            _ = first.sessions
    finally:
        first.close()
        second.close()
    assert not (scope.profile_home / 'state.db').exists()


def test_native_handles_share_store_and_release_only_their_acquisition(native_registry, core_pair):
    from hermes_db.errors import StorageClosedError
    registry, opened = native_registry
    scope = core_pair[0].scope
    first, second = registry.acquire(_settings(), scope), registry.acquire(_settings(), scope)
    try:
        assert first.sessions is second.sessions and len(opened) == 1
        first.sessions.create_session("s", "cli")
        epoch = first.runtime.begin_epoch(instance_id="owner")
        row = first.runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="one", payload={"text": "ask"})
        first.close()
        assert second.runtime.get_admission(admission_id=row["admission_id"])["target_session_id"] == "s"
        with pytest.raises(StorageClosedError):
            first.sessions
        assert not opened[0]._closed
    finally:
        first.close()
        second.close()
    assert opened[0]._closed
    with registry.acquire(_settings(), scope) as reopened:
        assert len(opened) == 2 and reopened.sessions.get_session("s")["id"] == "s"


def test_parallel_acquisition_builds_one_scoped_store(native_registry, core_pair):
    registry, opened = native_registry
    barrier = Barrier(6)

    def acquire():
        barrier.wait(10)
        return registry.acquire(_settings(), core_pair[0].scope)

    with ThreadPoolExecutor(max_workers=6) as pool:
        handles = list(pool.map(lambda _: acquire(), range(6)))
    try:
        assert len(opened) == 1 and len({id(handle.sessions) for handle in handles}) == 1
        other = registry.acquire(_settings(), core_pair[1].scope)
        try:
            assert other.sessions is not handles[0].sessions and len(opened) == 2
        finally:
            other.close()
    finally:
        for handle in handles:
            handle.close()


def test_failed_pg_acquisition_never_creates_a_local_database(native_registry, core_pair, monkeypatch):
    from hermes_db.errors import StorageUnavailableError
    registry, opened = native_registry

    def unavailable(settings, scope):
        raise StorageUnavailableError("injected connection failure")

    monkeypatch.setattr(registry, "_construct_store", unavailable)
    with pytest.raises(StorageUnavailableError):
        registry.acquire(_settings(), core_pair[0].scope)
    assert opened == [] and not (core_pair[0].scope.profile_home / "state.db").exists()


def test_profile_unserve_invalidates_held_resources_and_reopens_one_generation(native_registry, core_pair):
    from gateway.session_db_recovery import RecoverableHandleCache
    from hermes_db.errors import StorageClosedError
    from hermes_db.core.session_resource import SessionResource
    registry, opened = native_registry
    scope = core_pair[0].scope
    cache = RecoverableHandleCache()
    path = scope.profile_home / "state.db"

    def acquire():
        return SessionResource(registry.acquire(_settings(), scope))

    first = cache.get(path, acquire)
    first.create_session("keep", "cli")
    assert registry.close_all(scope.profile_home) == 1
    with pytest.raises(StorageClosedError):
        first.get_session("keep")
    second = cache.get(path, acquire)
    try:
        assert second is not first and len(opened) == 2
        first.close()
        assert second.get_session("keep")["id"] == "keep"
    finally:
        cache.close_all(lambda db: db.close())


def test_ordinary_profile_close_invalidates_only_its_native_resources(native_registry, core_pair):
    from hermes_db.access import close_session_resources_under, session_store_is_live
    from hermes_db.core.session_resource import SessionResource
    registry, _ = native_registry
    first = SessionResource(registry.acquire(_settings(), core_pair[0].scope))
    second = SessionResource(registry.acquire(_settings(), core_pair[1].scope))
    try:
        assert close_session_resources_under(core_pair[0].scope.profile_home) == 1
        assert not session_store_is_live(first) and session_store_is_live(second)
        first.close()
        second.create_session("still-live", "cli")
        assert second.get_session("still-live")["id"] == "still-live"
    finally:
        first.close()
        second.close()
