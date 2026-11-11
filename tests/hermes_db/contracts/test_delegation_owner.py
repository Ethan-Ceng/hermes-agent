"""Owner ledger persistence, recovery CAS, retention and scope contracts."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def _ledger(store):
    from hermes_cli.db_runtime import create_runtime_store
    return create_runtime_store(store).delegations


def _dispatch(ledger, delegation_id="d", *, timestamp=10):
    ledger.dispatch({"delegation_id": delegation_id, "session_key": "key", "parent_session_id": "s",
                     "origin_ui_session_id": "s", "origin_session_id": "s", "dispatched_at": timestamp},
                    owner_pid=1, owner_started_at=1, task={"goal": "work"})


def test_owner_partial_recovery_uses_fresh_snapshot_and_keeps_completed_results(core_pair):
    ledger = _ledger(core_pair[0])
    _dispatch(ledger)
    stale = ledger.running_records()[0]
    ledger.child("d", {"task_index": 0, "summary": "finished"})
    event = {"delegation_id": "d", "type": "async_delegation", "status": "unknown"}
    assert not ledger.recover_record(stale, event, {"summary": "outdated"})
    fresh = ledger.running_records()[0]
    result = {"results": [{"task_index": 0, "summary": "finished"}]}
    assert ledger.recover_record(fresh, event, result)
    assert ledger.get("d")["result"] == result and ledger.get("d")["state"] == "unknown"
    assert not ledger.recover_record(fresh, event, {})


def test_owner_delivery_claim_defer_ack_and_requeue_budget(core_pair):
    ledger = _ledger(core_pair[0])
    _dispatch(ledger)
    ledger.complete({"delegation_id": "d", "status": "completed", "completed_at": 20}, {"summary": "exact\x00"})
    assert ledger.claim("d", "a") and not ledger.claim("d", "b")
    assert not ledger.delivery("d", "b", "ack", attempt_cap=2)
    assert ledger.delivery("d", "a", "defer", attempt_cap=2)
    assert ledger.get("d")["delivery_attempts"] == 0
    assert ledger.claim("d", "b") and ledger.delivery("d", "b", "ack", attempt_cap=2)
    assert ledger.requeue_admitted("d", attempt_cap=2)["delivery_state"] == "pending"
    assert ledger.claim("d", "c") and ledger.delivery("d", "c", "ack", attempt_cap=2)
    assert ledger.requeue_admitted("d", attempt_cap=2) is None
    assert ledger.get("d")["delivery_state"] == "dropped"
    assert ledger.get("d")["result"] == {"summary": "exact\x00"}
    with pytest.raises(RuntimeStoreError, match="not_found"):
        ledger.claim("missing", "token")


def test_owner_queries_retention_and_expiry_do_not_touch_other_stores(core_pair):
    one, two = [_ledger(store) for store in core_pair]
    for ledger in (one, two):
        _dispatch(ledger)
        ledger.complete({"delegation_id": "d", "status": "error", "completed_at": 20}, {"error": "failed"})
    assert len(one.failed_records(parent_session_id="s", cutoff=0)) == 1
    assert one.failed_records(parent_session_id="foreign", cutoff=0) == []
    assert one.drop_expired("d", now=100, max_age_seconds=50)
    assert not one.pending_completions() and len(two.pending_completions()) == 1
    one.prune(retention_seconds=10000, max_completed=0, max_pending=0)
    assert one.get("d") is None and two.get("d") is not None
