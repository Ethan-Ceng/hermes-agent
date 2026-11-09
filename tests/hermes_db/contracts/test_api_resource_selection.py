"""Responses composition keeps native resource ownership and routed scope together."""

from types import SimpleNamespace

import pytest

from hermes_db.errors import StorageClosedError, StorageError


def _configure(db):
    home = db.scope.profile_home
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {db.scope.store_id}\n")
    (home / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/db\n")
    return home


def _no_sqlite(**kwargs):
    pytest.fail("A configured PG response store must never open SQLite")


def test_routed_responses_share_native_storage_but_close_only_owned_handles(native_registry, core_pair, monkeypatch):
    from gateway.platforms.api_server_storage_resources import (
        initialize_response_state, current_response_store, drain_response_stores,
    )
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db import factory
    registry, _ = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope))
    homes = [_configure(db) for db in core_pair]
    settings, scope = resolve_db_configuration(homes[0])
    primary = registry.acquire(settings.postgresql, scope)
    adapter = SimpleNamespace()
    first_token = set_hermes_home_override(homes[0])
    try:
        def no_constructor_transaction():
            raise AssertionError("Profile response selection must defer PG work to the persistence worker")

        with monkeypatch.context() as patch:
            patch.setattr(primary.sessions, "_write", no_constructor_transaction)
            initialize_response_state(adapter, _no_sqlite)
        current_response_store(adapter).put("same", {"output": "alpha"})
        second_token = set_hermes_home_override(homes[1])
        try:
            current_response_store(adapter).put("same", {"output": "beta"})
            assert current_response_store(adapter).get("same")["output"] == "beta"
        finally:
            reset_hermes_home_override(second_token)
        assert current_response_store(adapter).get("same")["output"] == "alpha"
        stores = drain_response_stores(adapter)
        assert len(stores) == 2
        for store in stores:
            store.close()
        with pytest.raises(StorageClosedError):
            current_response_store(adapter)
        primary.sessions.create_session("still-open", "cli")
        assert primary.sessions.get_session("still-open")["id"] == "still-open"
    finally:
        for store in drain_response_stores(adapter):
            store.close()
        primary.close()
        reset_hermes_home_override(first_token)
    assert all(not list(home.glob("*.db")) for home in homes)


def test_pg_response_acquisition_refusal_never_uses_a_file_store(core_pair, unavailable_native):
    from hermes_db.integration.api_resources import open_response_store
    home = _configure(core_pair[0])
    with pytest.raises(StorageError):
        open_response_store(home, _no_sqlite)
    assert not list(home.glob("*.db"))


def test_native_admission_lookup_reuses_the_response_connection_and_rejects_another_scope(core_pair, monkeypatch):
    from gateway.platforms.api_server_response_admissions import _lookup_admission
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
    from hermes_state_runtime import RuntimeStoreError
    db, other = core_pair
    db.create_session("s", "api_server")
    runtime = PostgresRuntimeStore(db)
    epoch = runtime.begin_epoch(instance_id="owner")
    accepted = runtime.admit_input(epoch=epoch, principal_id="api", session_id="s", request_id="request", payload={"text": "ask"})
    responses = PostgresResponseStore(db)
    owner = SimpleNamespace(db=db, profile_id=str(db.scope.profile_home))
    responses.bind_request_key("key", "fingerprint")

    def no_second_connection():
        raise AssertionError("A second session read would deadlock a one-connection pool")

    try:
        monkeypatch.setattr(db, "_read", no_second_connection)
        found = responses.atomically(_lookup_admission, owner, responses, ("key", "fingerprint"), "request")
        assert found[2]["admission_id"] == accepted["admission_id"]
        foreign = SimpleNamespace(db=other, profile_id=owner.profile_id)
        with pytest.raises(RuntimeStoreError, match="profile_mismatch"):
            responses.atomically(_lookup_admission, foreign, responses, ("key", "fingerprint"), "request")
    finally:
        responses.close()


def test_response_resource_reopens_after_a_profile_generation_is_retired(native_registry, core_pair, monkeypatch):
    from gateway.platforms.api_server_storage_resources import (
        initialize_response_state, current_response_store, drain_response_stores,
    )
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db import factory
    from hermes_db.access import close_session_resources_under
    registry, _ = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope))
    home = _configure(core_pair[0])
    token = set_hermes_home_override(home)
    adapter = SimpleNamespace()
    try:
        initialize_response_state(adapter, _no_sqlite)
        original = current_response_store(adapter)
        original.put("retained", {"body": "kept"})
        assert close_session_resources_under(home) == 1
        replacement = current_response_store(adapter)
        assert replacement is not original
        assert replacement.get("retained") == {"body": "kept"}
    finally:
        for store in drain_response_stores(adapter):
            store.close()
        reset_hermes_home_override(token)
