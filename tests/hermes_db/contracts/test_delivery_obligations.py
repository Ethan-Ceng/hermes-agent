"""Gateway obligations retain content, retry causes and exact claimant ownership."""

import time

import pytest


@pytest.fixture
def ledger(store, monkeypatch):
    from hermes_state import SessionDB
    if isinstance(store, SessionDB):
        from gateway import delivery_ledger
        monkeypatch.setattr(delivery_ledger, "_db_path", lambda: store.db_path)
        return delivery_ledger
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    return PostgresDeliveryLedger(store, instance_id="owner", lease_ttl_seconds=30)


def _row(store, ledger, oid):
    from hermes_state import SessionDB
    if isinstance(store, SessionDB):
        with ledger._connect() as conn:
            row = conn.execute("SELECT state,attempts,content,last_error FROM delivery_obligations WHERE obligation_id=?", (oid,)).fetchone()
        return dict(zip(("state", "attempts", "content", "last_error"), row)) if row else None
    return ledger.get_obligation(oid)


def test_delivery_dedupes_content_and_preserves_flood_runtime_retry_budget(store, ledger, monkeypatch):
    from gateway.delivery_ledger import FLOOD_MARKER
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    args = dict(obligation_id="id", session_key="agent:owner:telegram:chat", platform="telegram", chat_id="chat", thread_id=None,
        content="exact\x00reply", adapter_profile="owner")
    proof = ledger.record_obligation(**args)
    ledger.record_obligation(**args)
    claim = proof if proof is not None else "id"
    assert _row(store, ledger, "id")["content"] == "exact\x00reply"
    ledger.mark_attempting(claim)
    ledger.mark_failed(claim, "flood_control:5")
    assert ledger.sweep_failed_for_runtime("telegram", now=1000001.0, profile="owner") == []
    claimed = ledger.sweep_failed_for_runtime("telegram", now=1000010.0, profile="owner")
    assert len(claimed) == 1 and claimed[0]["attempts"] == 1 and claimed[0]["marker"] == FLOOD_MARKER
    assert ledger.release_runtime_claim(claimed[0].get("_claim", "id"), "flood_control:5")
    assert _row(store, ledger, "id")["attempts"] == 0
    assert ledger.sweep_failed_for_runtime("telegram", now=1000010.0, profile="other") == []


def test_core_expired_claim_is_replaced_and_late_owner_cannot_settle(core_pair, monkeypatch):
    from gateway import delivery_ledger as native
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger

    def no_pid_probe(*args):
        raise AssertionError("a PostgreSQL claimant is not a local PID")

    monkeypatch.setattr(native, "_owner_alive", no_pid_probe)
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    first = PostgresDeliveryLedger(core_pair[0], instance_id="first", lease_ttl_seconds=30)
    successor = PostgresDeliveryLedger(core_pair[0], instance_id="successor", lease_ttl_seconds=30)
    other = PostgresDeliveryLedger(core_pair[1], instance_id="other", lease_ttl_seconds=30)
    args = dict(obligation_id="same", session_key="route", platform="telegram", chat_id="chat", thread_id=None, content="reply")
    old_claim = first.record_obligation(**args)
    other.record_obligation(**args)
    first.mark_attempting(old_claim)
    assert successor.sweep_recoverable(now=1000001.0) == []
    monkeypatch.setattr(time, "time", lambda: 1000031.0)
    claimed = successor.sweep_recoverable()
    assert len(claimed) == 1 and claimed[0]["needs_marker"]
    assert not first.mark_delivered(old_claim)
    assert successor.mark_delivered(claimed[0]["_claim"])
    assert successor.get_obligation("same")["state"] == "delivered"
    assert other.get_obligation("same")["state"] == "pending"


def test_crash_left_reply_is_deduped_and_recovered_with_marker(store, ledger, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    args = dict(session_key="route", platform="telegram", chat_id="chat", thread_id=None, content="reply\x00", since=999990.0)
    ledger.record_crash_left_reply(obligation_id="crash", **args)
    ledger.record_crash_left_reply(obligation_id="duplicate", **args)
    assert _row(store, ledger, "duplicate") is None
    claimed = ledger.sweep_recoverable(now=1000001.0)
    assert len(claimed) == 1 and claimed[0]["needs_marker"] and claimed[0]["content"] == "reply\x00"


def test_core_runtime_claim_replaces_own_old_token_and_obeys_flood_adoption(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.delivery_ledger import PostgresDeliveryLedger
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    first = PostgresDeliveryLedger(core_pair[0], instance_id="first", lease_ttl_seconds=1)
    next_boot = PostgresDeliveryLedger(core_pair[0], instance_id="next", lease_ttl_seconds=30)
    proof = first.record_obligation(obligation_id="wait", session_key="route", platform="telegram", chat_id="chat",
        thread_id=None, content="reply", adapter_profile="bot")
    first.mark_failed(proof, "flood_control:50")
    assert next_boot.sweep_recoverable(now=1000002.0, deliverable_targets={("telegram", "other")}) == []
    adopted = next_boot.sweep_recoverable(now=1000002.0, deliverable_targets={("telegram", "bot")})
    assert len(adopted) == 1 and adopted[0]["adopted"] and adopted[0]["attempts"] == 0
    assert next_boot.pending_retries(now=1000002.0) == [{"platform": "telegram", "profile": "bot", "not_before": 1000050.0}]
    monkeypatch.setattr(time, "time", lambda: 1000051.0)
    claim = next_boot.sweep_failed_for_runtime("telegram", profile="bot")[0]
    assert not first.mark_delivered(proof)
    assert not next_boot.mark_delivered(adopted[0]["_claim"])
    assert next_boot.mark_failed(claim["_claim"], "send_path_degraded")
    replacement = next_boot.sweep_failed_for_runtime("telegram", profile="bot")[0]
    assert not next_boot.mark_delivered(claim["_claim"])
    assert next_boot.mark_delivered(replacement["_claim"])


def test_delivery_budget_staleness_and_terminal_first_retention(store, ledger, monkeypatch):
    from gateway import delivery_ledger as policy
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    args = dict(session_key="route", platform="telegram", chat_id="chat", thread_id=None, content="reply")
    monkeypatch.setattr(policy, "_MAX_ROWS", 2)
    proof = ledger.record_obligation(obligation_id="done", **args)
    ledger.mark_delivered(proof or "done")
    ledger.record_obligation(obligation_id="hold", **args)
    proof = ledger.record_obligation(obligation_id="retry", **args)
    assert _row(store, ledger, "done") is None
    claim = proof or "retry"
    for expected in range(1, policy.MAX_ATTEMPTS + 1):
        ledger.mark_failed(claim, "send_path_degraded")
        claimed = ledger.sweep_failed_for_runtime("telegram", now=1000001.0)
        assert len(claimed) == 1 and claimed[0]["attempts"] == expected
        claim = claimed[0].get("_claim", "retry")
    ledger.mark_failed(claim, "send_path_degraded")
    assert ledger.sweep_failed_for_runtime("telegram", now=1000001.0) == []
    assert _row(store, ledger, "retry")["state"] == "abandoned"
    ledger.record_crash_left_reply(obligation_id="stale", **args, since=1000001.0)
    assert ledger.sweep_recoverable(now=1000001.0 + policy.STALE_AFTER_SECONDS) == []
    assert _row(store, ledger, "stale")["state"] == "abandoned"
