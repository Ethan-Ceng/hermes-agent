"""Canonical runtime contracts and independent-connection races on real PG."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.hermes_db.contracts import test_runtime as contracts
from tests.hermes_db.contracts import test_runtime_isolation as isolation

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    contracts.test_request_retry_payload_conflict_fifo_and_generation,
    contracts.test_restart_never_replays_started_work_and_fences_old_epoch,
    contracts.test_queue_cap_cancellation_and_exact_retry_are_consistent,
    contracts.test_steer_revert_and_terminal_transfer_are_once_only,
    contracts.test_unknown_resolution_requires_explicit_generation_and_never_requeues,
    contracts.test_rehome_and_automation_retarget_keep_fifo_and_identity,
]
ISOLATION = [
    isolation.test_same_schema_runtime_identity_and_epoch_are_scoped,
    isolation.test_worker_on_compression_child_blocks_logical_parent_but_not_branch,
    isolation.test_core_effect_refusal_rolls_back_and_replay_bypasses_new_write_guard,
    isolation.test_claim_mark_follows_local_reset_target_and_ignores_other_store,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_runtime_contract_on_postgresql(pg_store, pg_runtime, contract):
    contract(pg_store, pg_runtime)


@pytest.mark.parametrize("contract", ISOLATION, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_same_schema_runtime_isolation(pg_store, tmp_path, contract):
    from hermes_db.scope import DatabaseScope
    from hermes_db.integration.session_composition import create_session_store
    peer = create_session_store(pg_store._transactions, DatabaseScope(tmp_path / "other", "other-store"))
    try:
        contract([pg_store, peer])
    finally:
        peer.close()


def test_independent_admissions_and_claims_never_duplicate(pg_store, pg_runtime):
    pg_store.create_session("s", "test")
    epoch = pg_runtime.begin_epoch(instance_id="owner")
    gate = Barrier(2)
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={"text": "ask"})

    def admit():
        gate.wait(15)
        return pg_runtime.admit_input(**args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit) for _ in range(2)]
        rows = [future.result(20) for future in futures]
    assert rows[0] == rows[1]
    gate = Barrier(2)

    def claim():
        gate.wait(15)
        return pg_runtime.claim_input(epoch=epoch, session_id="s")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        claimed = [future.result(20) for future in futures]
    assert sum(row is None for row in claimed) == 1
    assert next(row for row in claimed if row)["admission_id"] == rows[0]["admission_id"]


def test_queue_capacity_is_atomic_under_competing_requests(pg_store, pg_runtime):
    from hermes_state_runtime import ADMISSION_QUEUE_MAX, RuntimeStoreError
    pg_store.create_session("s", "test")
    epoch = pg_runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="s", payload={"text": "ask"})
    for index in range(ADMISSION_QUEUE_MAX - 1):
        pg_runtime.admit_input(**args, request_id=str(index))
    gate = Barrier(2)

    def admit(request_id):
        gate.wait(15)
        try:
            return pg_runtime.admit_input(**args, request_id=request_id)["status"]
        except RuntimeStoreError as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit, request_id) for request_id in ("last-a", "last-b")]
        outcomes = [future.result(20) for future in futures]
    assert sorted(outcomes) == ["queue_full", "queued"]
    assert len(pg_runtime.list_admissions(session_id="s")) == ADMISSION_QUEUE_MAX
