"""Real PostgreSQL delivery contracts and atomic competing claims."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

import pytest

from tests.hermes_db.contracts import test_delivery_gateway as gateway_contracts
from tests.hermes_db.contracts import test_delivery_obligations as contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize("contract", [contracts.test_delivery_dedupes_content_and_preserves_flood_runtime_retry_budget,
    contracts.test_crash_left_reply_is_deduped_and_recovered_with_marker,
    contracts.test_delivery_budget_staleness_and_terminal_first_retention], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_delivery_contract_on_postgresql(pg_store, monkeypatch, contract):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    contract(pg_store, PostgresDeliveryLedger(pg_store, instance_id="owner", lease_ttl_seconds=30), monkeypatch)


@pytest.mark.parametrize("contract", [contracts.test_core_expired_claim_is_replaced_and_late_owner_cannot_settle,
    contracts.test_core_runtime_claim_replaces_own_old_token_and_obeys_flood_adoption,
    gateway_contracts.test_core_delivery_unknown_commit_keeps_uncertain_send_marked,
    gateway_contracts.test_core_delivery_rollback_never_leaves_a_partial_obligation], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_delivery_scopes_and_failure_on_postgresql(pg_pair, monkeypatch, contract):
    contract(pg_pair, monkeypatch)


@pytest.mark.asyncio
async def test_gateway_delivery_on_postgresql(pg_pair, monkeypatch):
    await gateway_contracts.test_core_gateway_uses_process_scope_and_retains_claim_across_send(pg_pair, monkeypatch)


def _race(*actions):
    gate = Barrier(len(actions))

    def invoke(action):
        gate.wait(15)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return [result.result(30) for result in [pool.submit(invoke, action) for action in actions]]


def test_two_boot_sweeps_have_one_claimant_and_late_ack_cannot_settle(pg_store, monkeypatch):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    old = PostgresDeliveryLedger(pg_store, instance_id="old", lease_ttl_seconds=1)
    proof = old.record_obligation(obligation_id="race", session_key="route", platform="slack", chat_id="chat", thread_id=None, content="reply")
    old.mark_attempting(proof)
    first, second = [PostgresDeliveryLedger(pg_store, instance_id=name) for name in ("first", "second")]
    claims = _race(lambda: first.sweep_recoverable(now=1000002.0), lambda: second.sweep_recoverable(now=1000002.0))
    assert sorted(map(len, claims)) == [0, 1]
    assert not old.mark_delivered(proof)
    assert pg_store._transactions.engine.pool.checkedout() == 0


def test_two_runtime_sweeps_spend_one_attempt(pg_store, monkeypatch):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    ledger = PostgresDeliveryLedger(pg_store, instance_id="owner")
    proof = ledger.record_obligation(obligation_id="race", session_key="route", platform="slack", chat_id="chat", thread_id=None, content="reply")
    ledger.mark_failed(proof, "send_path_degraded")
    claims = _race(lambda: ledger.sweep_failed_for_runtime("slack"), lambda: ledger.sweep_failed_for_runtime("slack"))
    assert sorted(map(len, claims)) == [0, 1]
    assert ledger.get_obligation("race")["attempts"] == 1


def test_parallel_crash_reply_registration_does_not_duplicate(pg_store):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    ledger = PostgresDeliveryLedger(pg_store)
    args = dict(session_key="route", platform="slack", chat_id="chat", thread_id=None, content="reply", since=time.time() - 10)
    _race(lambda: ledger.record_crash_left_reply(obligation_id="first", **args),
        lambda: ledger.record_crash_left_reply(obligation_id="second", **args))
    assert sum(ledger.get_obligation(oid) is not None for oid in ("first", "second")) == 1
