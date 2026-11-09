"""Ordinary gateway producers and recovery carry the same immutable PG claim."""

from contextlib import contextmanager
import time

import pytest


@pytest.mark.asyncio
async def test_core_gateway_uses_process_scope_and_retains_claim_across_send(core_pair, monkeypatch):
    from gateway import delivery_backend, delivery_ledger as dl
    from gateway.platforms.base import SendResult
    from hermes_cli import db_setup
    from hermes_db import factory
    from hermes_db.domains.runtime.postgres.delivery_claim import DeliveryClaim
    from hermes_db.handle import DatabaseHandle
    from hermes_db.settings import DatabaseSettings, PostgresSettings
    from tests.gateway.test_delivery_ledger_process_home import _ServedAdapter, _runner
    from tests.gateway.test_delivery_ledger_producer import _event

    owner, served = core_pair
    monkeypatch.setenv("HERMES_HOME", str(owner.scope.profile_home))
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    monkeypatch.setattr(delivery_backend, "_ledgers", {})
    settings = DatabaseSettings("postgresql", PostgresSettings("postgresql://unused", "test"))
    closed, opened = [], []

    def resolve(home):
        assert home.resolve() == owner.scope.profile_home
        return settings, owner.scope

    def acquire(config, scope):
        assert config == settings and scope == owner.scope
        opened.append(scope)
        return DatabaseHandle(scope, owner, None, lambda: closed.append(scope))

    def forbid_sqlite():
        raise AssertionError("a PostgreSQL delivery may not fall back to SQLite")

    monkeypatch.setattr(db_setup, "resolve_db_configuration", resolve)
    monkeypatch.setattr(factory, "acquire_db", acquire)
    monkeypatch.setattr(dl, "_connect", forbid_sqlite)
    adapter, event = _ServedAdapter(), _event()
    runner = _runner(adapter)
    active = []
    original_write, original_send = owner._write, adapter.send

    @contextmanager
    def track_write():
        with original_write() as conn:
            active.append(conn)
            try:
                yield conn
            finally:
                active.remove(conn)

    async def send(**kwargs):
        assert not active, "the platform send must not hold a database transaction"
        return await original_send(**kwargs)

    monkeypatch.setattr(owner, "_write", track_write)
    monkeypatch.setattr(adapter, "send", send)
    try:
        with served._profile.activate():
            proof = await adapter._record_delivery_obligation(event, "route", "reply", adapter, False)
            assert isinstance(proof, DeliveryClaim) and proof.store_id == owner.scope.store_id
            await adapter._finalize_delivery_obligation(proof, SendResult(success=False, error="send_path_degraded"), event, adapter)
            claimed = dl.sweep_failed_for_runtime("slack", profile="research")
            assert len(claimed) == 1 and claimed[0]["_claim"] != proof
            await adapter._finalize_delivery_obligation(proof, SendResult(success=True), event, adapter)
            assert delivery_backend.postgres_ledger().get_obligation(str(proof))["state"] == "attempting"
            assert await runner._redeliver_claimed_obligations(claimed) == 1
            assert delivery_backend.postgres_ledger().get_obligation(str(proof))["state"] == "delivered"
        assert len(opened) == 1
        assert adapter.sent == [dl.RECONNECTED_MARKER + "reply"]
    finally:
        delivery_backend.close_delivery_handles()
    assert closed == [owner.scope]
    owner.create_session("still-open", "cli")


def test_core_delivery_unknown_commit_keeps_uncertain_send_marked(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    from hermes_db.errors import UnknownCommitError
    owner = core_pair[0]
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    ledger = PostgresDeliveryLedger(owner, instance_id="old", lease_ttl_seconds=1)
    proof = ledger.record_obligation(obligation_id="lost", session_key="route", platform="slack", chat_id="chat", thread_id=None, content="reply")
    original = owner._write

    @contextmanager
    def lose_ack():
        with original() as conn:
            yield conn
        raise UnknownCommitError("injected acknowledgement loss")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_write", lose_ack)
        with pytest.raises(UnknownCommitError):
            ledger.mark_attempting(proof)
    successor = PostgresDeliveryLedger(owner, instance_id="new", lease_ttl_seconds=1)
    claimed = successor.sweep_recoverable(now=1000002.0)
    assert len(claimed) == 1 and claimed[0]["needs_marker"]
    assert not ledger.mark_delivered(proof)


def test_core_delivery_rollback_never_leaves_a_partial_obligation(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    from hermes_db.domains.runtime.postgres.queries import deliveries
    ledger = PostgresDeliveryLedger(core_pair[0])

    def fail(*args):
        raise RuntimeError("injected prune failure")

    with monkeypatch.context() as patch:
        patch.setattr(deliveries, "prune", fail)
        with pytest.raises(RuntimeError, match="injected"):
            ledger.record_obligation(obligation_id="rollback", session_key="route", platform="slack", chat_id="chat", thread_id=None, content="reply")
    assert ledger.get_obligation("rollback") is None
