"""Worker and delegation contracts on a real explicitly configured PG service."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.hermes_db.contracts import test_workers as contracts
from tests.hermes_db.contracts import test_worker_metadata as metadata
from tests.hermes_db.contracts import test_worker_atomicity as atomicity
from tests.hermes_db.contracts import test_delegations as delegations
from tests.hermes_db.contracts import test_delegation_owner as owner

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    contracts.test_worker_receipts_fence_assignment_sequence_and_duplicate_effects,
    contracts.test_worker_restart_requires_private_adoption_and_preserves_receipts,
    contracts.test_worker_context_reads_keep_revision_and_are_retired_at_finish,
    metadata.test_worker_constructor_prompt_pin_and_sidecar_allowlist,
    metadata.test_worker_title_conflict_receipt_authorizes_later_numbering,
    metadata.test_worker_row_sidecars_usage_and_lifecycle_stay_on_owned_transcript,
    metadata.test_worker_turn_lease_holder_fences_transcript_writes,
    delegations.test_delegation_receipts_complete_and_delivery_claims_are_atomic,
    delegations.test_delegation_cannot_forge_parent_route_and_unscheduled_retries_are_once,
]
PAIR_CONTRACTS = [
    atomicity.test_child_reservation_capacity_and_parent_finish_close_children,
    atomicity.test_worker_ids_and_receipts_do_not_cross_stores,
    owner.test_owner_partial_recovery_uses_fresh_snapshot_and_keeps_completed_results,
    owner.test_owner_delivery_claim_defer_ack_and_requeue_budget,
    owner.test_owner_queries_retention_and_expiry_do_not_touch_other_stores,
]


@pytest.fixture
def pg_pair(pg_store, tmp_path):
    from hermes_db.scope import DatabaseScope
    from hermes_db.session_store import PostgresSessionStore
    peer = PostgresSessionStore(pg_store._transactions, DatabaseScope(tmp_path / "other", "other-store"))
    try:
        yield [pg_store, peer]
    finally:
        peer.close()


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_worker_contract_on_postgresql(pg_store, pg_runtime, contract):
    contract(pg_store, pg_runtime)


@pytest.mark.parametrize("contract", PAIR_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_scoped_worker_contract_on_postgresql(pg_pair, contract):
    contract(pg_pair)


def test_worker_receipt_rollback_on_postgresql(pg_pair, monkeypatch):
    atomicity.test_receipt_failure_rolls_back_transcript_counters_and_sequence(pg_pair, monkeypatch)


def test_competing_worker_receipts_commit_one_effect(pg_store, pg_runtime):
    pg_store.create_session("s", "cli")
    epoch = pg_runtime.begin_epoch(instance_id="owner")
    assignment = dict(epoch=epoch, execution_id="worker", session_id="s", generation=0)
    pg_runtime.register_worker(**assignment, kind="compute", adoption_secret="private-test")
    args = dict(**assignment, sequence=1, operation="transcript.append", payload={"messages": [{"role": "assistant", "content": "once"}]})
    gate = Barrier(2)

    def mutate():
        gate.wait(15)
        return pg_runtime.mutate_worker(**args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mutate) for _ in range(2)]
        results = [future.result(20) for future in futures]
    assert results[0] == results[1] and pg_store.message_count("s") == 1
