"""API Run background updates retain their authenticated store and API scope."""

from hermes_cli.db_sessions import _build_session_resources

import pytest

from hermes_db.errors import StorageError


def _configure(db):
    home = db.scope.profile_home
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("storage:\n  backend: postgresql\n  postgresql:\n"
        f"    schema: hermes\n    store_id: {db.scope.store_id}\n")
    (home / ".env").write_text("HERMES_POSTGRES_DSN=postgresql://unused/db\n")
    return home


def _no_sqlite(**kwargs):
    pytest.fail("PG runs must never open SQLite or an in-memory reservation store")


def test_run_updates_use_the_authenticated_scope_after_a_profile_context_switch(native_registry, core_pair, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli import db_sessions as factory
    from gateway.platforms.api_server_run_resources import ProfileRunStores
    registry, _ = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope, build=_build_session_resources))
    homes = [_configure(db) for db in core_pair]
    token = set_hermes_home_override(homes[0])
    resources = None
    try:
        resources = ProfileRunStores(_no_sqlite)
        assert resources.durable
        resources.reserve("first-api-scope", "key", "digest", "same-run", {"status": "queued"})
        second = set_hermes_home_override(homes[1])
        try:
            resources.reserve("second-api-scope", "key", "digest", "same-run", {"status": "queued"})
            resources.update_status("same-run", {"status": "completed", "output": "first"}, scope="first-api-scope")
            assert resources.status_for_run("second-api-scope", "same-run")["status"]["status"] == "queued"
            with pytest.raises(StorageError):
                resources.update_status("same-run", {"status": "failed"}, scope="unknown-scope")
        finally:
            reset_hermes_home_override(second)
        assert resources.status_for_run("first-api-scope", "same-run")["status"]["output"] == "first"
    finally:
        if resources is not None:
            resources.close()
        reset_hermes_home_override(token)
    assert all(not list(home.glob("*.db")) for home in homes)


def test_run_pg_factory_refusal_never_uses_memory_or_sqlite(core_pair, unavailable_native):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from gateway.platforms.api_server_run_resources import ProfileRunStores
    home = _configure(core_pair[0])
    token = set_hermes_home_override(home)
    try:
        with pytest.raises(StorageError):
            ProfileRunStores(_no_sqlite)
    finally:
        reset_hermes_home_override(token)
    assert not list(home.glob("*.db"))


def test_close_admission_uses_routed_owner_and_survives_resource_reacquisition(native_registry, core_pair, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli import db_sessions as factory
    from gateway.platforms.api_server_run_resources import ProfileRunStores
    registry, _ = native_registry
    monkeypatch.setattr(factory, 'acquire_db', lambda settings, scope: registry.acquire(settings.postgresql, scope, build=_build_session_resources))
    homes = [_configure(db) for db in core_pair]
    token = set_hermes_home_override(homes[0])
    resources = None
    try:
        resources = ProfileRunStores(_no_sqlite)
        assert resources.find_or_close('first-scope', 'closed') == ('closed', None)
        foreign = set_hermes_home_override(homes[1])
        try:
            with pytest.raises(StorageError, match='another profile'):
                resources.find_or_close('first-scope', 'closed')
            assert resources.reserve('second-scope', 'closed', 'body', 'run', {'status': 'running'})[0] == 'created'
            assert resources.find_or_close('second-scope', 'closed')[0] == 'found'
        finally:
            reset_hermes_home_override(foreign)
        resources.close()
        resources = ProfileRunStores(_no_sqlite)
        assert resources.find_or_close('first-scope', 'closed') == ('closed', None)
        assert resources.reserve('first-scope', 'closed', 'late', 'late-run', {'status': 'running'})[0] == 'conflict'
    finally:
        if resources is not None:
            resources.close()
        reset_hermes_home_override(token)


def test_native_api_auth_namespace_survives_local_home_and_profile_label_changes(core_pair, tmp_path):
    from types import SimpleNamespace
    from contextvars import ContextVar
    from gateway.platforms.api_server_runs import _run_idempotency_scope
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.scope import DatabaseScope
    from hermes_cli.db_sessions import create_session_store
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    first, other = core_pair
    alias = create_session_store(first._transactions, DatabaseScope(tmp_path / "renamed", first.scope.store_id))
    api = SimpleNamespace(_api_request_profile=ContextVar("profile-label", default="alpha"))
    scopes = []
    chats = []
    try:
        for db, name in ((first, "alpha"), (alias, "beta"), (other, "beta")):
            token = set_hermes_home_override(_configure(db))
            label = api._api_request_profile.set(name)
            response = PostgresResponseStore(db, initialize=False)
            adapter = SimpleNamespace(_room_grant_token=lambda request: None,
                _expected_api_key=lambda: "private-api-key", _current_response_store=lambda: response)
            try:
                scopes.append(_run_idempotency_scope(adapter, object(), _api_server=api))
                from gateway.platforms.api_server_storage_resources import chat_session_id
                chats.append(chat_session_id(adapter, "prompt", "opening", name))
            finally:
                response.close()
                api._api_request_profile.reset(label)
                reset_hermes_home_override(token)
    finally:
        alias.close()
    assert scopes[0] == scopes[1] and scopes[0] != scopes[2]
    assert chats[0] == chats[1] and chats[0] != chats[2]


def test_native_run_poll_uses_epoch_recovery_and_never_local_pid_liveness(native_registry, core_pair, monkeypatch):
    from types import SimpleNamespace
    from gateway.platforms import api_server_runs
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_cli import db_sessions as factory
    from gateway.platforms.api_server_run_resources import ProfileRunStores
    from hermes_cli.db_runtime import create_runtime_store
    db = core_pair[0]
    registry, _ = native_registry
    monkeypatch.setattr(factory, "acquire_db", lambda settings, scope: registry.acquire(settings.postgresql, scope, build=_build_session_resources))
    token = set_hermes_home_override(_configure(db))
    stores = ProfileRunStores(_no_sqlite)
    runtime = create_runtime_store(db)
    db.create_session("s", "api_server")

    def no_pid_probe(*args):
        raise AssertionError("The local PID cannot identify a remote PG runtime")

    monkeypatch.setattr(api_server_runs, "_owner_alive", no_pid_probe)
    authority = SimpleNamespace(db=db, profile_id="server-profile", sessions={}, retiring=False, retired=False)
    adapter = SimpleNamespace(gateway_runner=SimpleNamespace(session_authority=authority),
        _run_admission_aliases={}, _run_statuses={}, _run_idempotency_ids=set(), _run_owners={},
        _run_idempotency_store=stores, _run_idempotency_scope=lambda request: "scope")
    try:
        epoch = runtime.begin_epoch(instance_id="first-owner")
        runtime.admit_input(epoch=epoch, principal_id="api", session_id="s", request_id="canonical", payload={"text": "ask"})
        runtime.claim_input(epoch=epoch, session_id="s")
        epoch = runtime.begin_epoch(instance_id="second-owner")
        runtime.recover_inputs(epoch=epoch)
        polled = api_server_runs._durable_run_status(adapter, {}, "canonical")
        assert polled["status"] == "unknown" and polled["session_id"] == "s"
        stores.reserve("scope", "unadmitted", "fingerprint", "unadmitted", {"status": "running"}, owner_pid=123456)
        assert api_server_runs._durable_run_status(adapter, {}, "unadmitted")["status"] == "running"
    finally:
        stores.close()
        reset_hermes_home_override(token)
