"""API metadata remains isolated and queryable after rollback or a lost commit ack."""

from contextlib import contextmanager

import pytest


def test_core_response_api_scopes_and_stores_never_share_identity_or_bodies(core_pair):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    first, second = core_pair
    stores = [PostgresResponseStore(first, api_scope="one"), PostgresResponseStore(first, api_scope="two"),
              PostgresResponseStore(second, api_scope="one")]
    try:
        for index, store in enumerate(stores):
            assert store.bind_request_key("idem:key", str(index), model=f"model-{index}")
            store.bind_request_admission("idem:key", f"admission-{index}")
            store.put("response", {"private": index})
            store.set_conversation("main", "response")
        stores[0].delete("response")
        for index in (1, 2):
            assert stores[index].get("response") == {"private": index}
            assert stores[index].get_conversation("main") == "response"
            assert stores[index].request_admission("idem:key") == f"admission-{index}"
            assert stores[index].request_model("idem:key", "fallback") == f"model-{index}"
    finally:
        for store in stores:
            store.close()


def test_core_run_status_updates_require_authenticated_scope_and_store(core_pair):
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    stores = [PostgresRunIdempotencyStore(store) for store in core_pair]
    try:
        for store in stores:
            for scope in ("one", "two"):
                store.reserve(scope, "key", "digest", "same-run", {"status": "running"})
        stores[0].update_status("same-run", {"status": "completed"}, scope="one")
        assert stores[0].status_for_run("one", "same-run")["status"]["status"] == "completed"
        assert stores[0].status_for_run("two", "same-run")["status"]["status"] == "running"
        assert stores[1].status_for_run("one", "same-run")["status"]["status"] == "running"
    finally:
        for store in stores:
            store.close()


def test_core_response_failed_eviction_rolls_back_body_and_settlement(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    from hermes_db.domains.runtime.postgres.operations import api
    store = PostgresResponseStore(core_pair[0])
    try:
        store.bind_request_key("idem:key", "digest")

        def fail(*args):
            raise RuntimeError("injected eviction")

        with monkeypatch.context() as patch:
            patch.setattr(api, "evict", fail)
            with pytest.raises(RuntimeError, match="injected"):
                store.put("idem:key", {"response": {"id": "r"}})
        assert store.get("idem:key") is None
        assert store.request_created_at("idem:key") is not None
    finally:
        store.close()


def test_core_run_lost_commit_ack_is_observed_by_original_key_without_reserving_again(core_pair, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    sessions, _ = core_pair
    store = PostgresRunIdempotencyStore(sessions)
    original = sessions._write

    @contextmanager
    def lose_ack():
        with original() as conn:
            yield conn
        raise UnknownCommitError("injected acknowledgement loss")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sessions, "_write", lose_ack)
            with pytest.raises(UnknownCommitError):
                store.reserve("scope", "key", "digest", "original", {"status": "running"})
        outcome, row = store.lookup("scope", "key", "digest")
        assert outcome == "reused" and row["run_id"] == "original"
        assert store.reserve("scope", "key", "digest", "different", {"status": "queued"})[1]["run_id"] == "original"
    finally:
        store.close()


def test_core_response_identity_settles_from_same_store_retired_admission_without_observer(core_pair):
    from gateway.platforms.api_server_response_identity import durable_response_id
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    sessions, _ = core_pair
    sessions.create_session("s", "api_server")
    runtime = PostgresRuntimeStore(sessions)
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="api", session_id="s", request_id="r", payload={"text": "private\x00"})
    admitted = runtime.admit_input(**args)
    responses = PostgresResponseStore(sessions, max_size=0, max_identities=1)
    try:
        responses.bind_request_key("idem:r", "wire")
        responses.bind_request_admission("idem:r", admitted["admission_id"])
        runtime.cancel_input(epoch=epoch, admission_id=admitted["admission_id"])
        sessions.delete_session("s")
        assert responses.delete(durable_response_id("idem:r"))
        assert responses.request_created_at("idem:r") is None
        assert runtime.admit_input(**args)["status"] == "terminal"
    finally:
        responses.close()


def test_core_response_pointer_repair_uses_existing_transaction_and_never_reopens_canonical_store(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
    from hermes_state_runtime import RuntimeStoreError

    sessions, _ = core_pair
    sessions.create_session("s", "api_server")
    runtime = PostgresRuntimeStore(sessions)
    epoch = runtime.begin_epoch(instance_id="owner")
    admitted = runtime.admit_input(epoch=epoch, principal_id="api", session_id="s", request_id="request", payload={"text": "held"})
    responses = PostgresResponseStore(sessions)

    def forbid_read():
        raise AssertionError("a second connection would deadlock a one-connection pool")

    try:
        responses.bind_request_key("idem:key", "digest")
        with monkeypatch.context() as patch:
            patch.setattr(sessions, "_read", forbid_read)
            found = responses.atomically(responses.resolve_request_admission, "idem:key", "request")
        assert found["admission_id"] == admitted["admission_id"]
        assert responses.request_admission("idem:key") == admitted["admission_id"]
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            responses.resolve_request_admission("idem:key", "foreign-request")
    finally:
        responses.close()


@pytest.mark.asyncio
async def test_core_api_off_loop_binds_owner_and_closed_child_keeps_parent_open(core_pair):
    from hermes_constants import get_hermes_home
    from hermes_db.errors import StorageClosedError
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore

    first, second = core_pair
    response = PostgresResponseStore(first)
    with second._profile.activate():
        assert await response.off_loop(get_hermes_home) == first.scope.profile_home
    response.close()
    with pytest.raises(StorageClosedError):
        response.get("anything")
    first.create_session("still-open", "cli")
    assert first.get_session("still-open") is not None


def test_core_api_connection_failure_never_creates_memory_identity(core_pair, monkeypatch):
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore

    sessions, _ = core_pair
    runs = PostgresRunIdempotencyStore(sessions)

    @contextmanager
    def unavailable():
        raise StorageUnavailableError("injected connection failure")
        yield

    try:
        with monkeypatch.context() as patch:
            patch.setattr(sessions, "_write", unavailable)
            with pytest.raises(StorageUnavailableError):
                PostgresResponseStore(sessions)
            with pytest.raises(StorageUnavailableError):
                runs.reserve("scope", "key", "digest", "run", {"status": "queued"})
        assert runs.lookup("scope", "key", "digest") == ("missing", None)
    finally:
        runs.close()
