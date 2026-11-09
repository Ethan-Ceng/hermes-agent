"""Real PostgreSQL Responses/Run persistence, recovery and concurrent identity tests."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.hermes_db.contracts import test_api_responses as responses
from tests.hermes_db.contracts import test_api_run_idempotency as runs
from tests.hermes_db.contracts import test_api_scope_faults as faults

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def pg_response_factory(pg_store):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    children = []

    def create(**options):
        child = PostgresResponseStore(pg_store, **options)
        children.append(child)
        return child

    yield create
    for child in children:
        child.close()


@pytest.fixture
def pg_run_factory(pg_store):
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    children = []

    def create():
        child = PostgresRunIdempotencyStore(pg_store)
        children.append(child)
        return child

    yield create
    for child in children:
        child.close()


@pytest.mark.parametrize("contract", [responses.test_response_identity_model_and_output_order_survive_body_eviction_and_reopen,
    responses.test_response_retry_envelope_is_immutable_and_chained_body_remains_exact,
    responses.test_only_settled_response_identities_join_retention_bound,
    responses.test_zero_body_capacity_still_settles_and_bounds_request_identity], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_response_contract_on_postgresql(pg_response_factory, contract):
    contract(pg_response_factory)


def test_run_reopen_on_postgresql(pg_run_factory):
    runs.test_run_reservation_reopens_exact_identity_and_scopes_conflicts(pg_run_factory)


def test_run_retention_on_postgresql(pg_run_factory, monkeypatch):
    runs.test_run_retention_keeps_unsettled_and_extends_matching_terminal_grant(pg_run_factory, monkeypatch)


@pytest.mark.parametrize("contract", [faults.test_core_response_api_scopes_and_stores_never_share_identity_or_bodies,
    faults.test_core_run_status_updates_require_authenticated_scope_and_store,
    faults.test_core_response_identity_settles_from_same_store_retired_admission_without_observer], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_scope_and_terminal_api_on_postgresql(pg_pair, contract):
    contract(pg_pair)


@pytest.mark.parametrize("contract", [faults.test_core_response_failed_eviction_rolls_back_body_and_settlement,
    faults.test_core_run_lost_commit_ack_is_observed_by_original_key_without_reserving_again,
    faults.test_core_response_pointer_repair_uses_existing_transaction_and_never_reopens_canonical_store,
    faults.test_core_api_connection_failure_never_creates_memory_identity], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_api_failure_on_postgresql(pg_pair, monkeypatch, contract):
    contract(pg_pair, monkeypatch)


@pytest.mark.asyncio
async def test_api_off_loop_profile_on_postgresql(pg_pair):
    await faults.test_core_api_off_loop_binds_owner_and_closed_child_keeps_parent_open(pg_pair)


def _race(*actions):
    gate = Barrier(len(actions))

    def invoke(action):
        gate.wait(15)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(invoke, action) for action in actions]
        return [future.result(30) for future in futures]


def test_parallel_run_reservation_has_one_owner(pg_store):
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    first, second = PostgresRunIdempotencyStore(pg_store), PostgresRunIdempotencyStore(pg_store)
    try:
        result = _race(lambda: first.reserve("scope", "key", "digest", "first", {"status": "queued"}),
            lambda: second.reserve("scope", "key", "digest", "second", {"status": "queued"}))
        assert sorted(row[0] for row in result) == ["created", "reused"]
        assert result[0][1]["run_id"] == result[1][1]["run_id"]
    finally:
        first.close()
        second.close()


def test_parallel_output_indexes_have_one_order(pg_store):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    store = PostgresResponseStore(pg_store)
    try:
        store.bind_request_key("idem:key", "digest")
        assert _race(lambda: store.output_index("idem:key", "same"), lambda: store.output_index("idem:key", "same")) == [0, 0]
        assert sorted(_race(lambda: store.output_index("idem:key", "one"), lambda: store.output_index("idem:key", "two"))) == [1, 2]
    finally:
        store.close()


def test_parallel_terminal_observers_keep_first_envelope(pg_store):
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    store = PostgresResponseStore(pg_store)
    try:
        store.bind_request_key("idem:key", "digest")
        _race(lambda: store.put("idem:key", {"response": {"id": "r", "output": "one\x00"}}),
            lambda: store.put("idem:key", {"response": {"id": "r", "output": "two\x00"}}))
        assert store.get("idem:key")["response"]["output"] in ("one\x00", "two\x00")
    finally:
        store.close()
