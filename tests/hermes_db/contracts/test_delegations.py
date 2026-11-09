"""The delegation ledger shares its owner's ordered receipt stream."""

import os

import pytest

from hermes_state_runtime import RuntimeStoreError


def _ledger(store, runtime):
    import psutil
    from hermes_cli.process_identity import worker_birth
    from hermes_db.backends.sqlite.acquire import SQLiteRuntime

    store.create_session("s", "cli", session_key="key")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(epoch=epoch, execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(**assignment, kind="compute", adoption_secret="private-test")
    pid = os.getpid()
    birth = worker_birth(psutil.Process(pid))
    if isinstance(runtime, SQLiteRuntime):
        from gateway.session_worker_delegation import persist_worker_delegation
        def send(sequence, operation, payload):
            return persist_worker_delegation(runtime._db, **assignment, sequence=sequence, operation=operation,
                                             payload=payload, worker_pid=pid, worker_birth=birth)
    else:
        from hermes_db.domains.runtime.postgres.operations.worker_delegations import verify_owner
        owner = verify_owner("worker", pid, birth)
        def send(sequence, operation, payload):
            return runtime.persist_delegation(**assignment, sequence=sequence, operation=operation, payload=payload, owner=owner)
    return send


def _dispatch():
    return {"delegation_id": "d", "task": {"goal": "work"}, "dispatched_at": 10,
            "session_key": "key", "parent_session_id": "s", "origin_ui_session_id": "s", "origin_session_id": "s"}


def test_delegation_receipts_complete_and_delivery_claims_are_atomic(store, runtime):
    send = _ledger(store, runtime)
    payload = _dispatch()
    assert send(1, "delegation.dispatch", payload) == {"value": None}
    assert send(1, "delegation.dispatch", payload) == {"value": None}
    assert send(2, "delegation.read", {"delegation_id": "d"})["value"]["state"] == "running"
    assert send(3, "delegation.claim", {"delegation_id": "d", "claim_id": "early"}) == {"value": False}
    send(4, "delegation.child", {"delegation_id": "d", "entry": {"task_index": 0, "summary": "partial"}})
    event = {key: payload[key] for key in ("delegation_id", "session_key", "parent_session_id", "origin_ui_session_id", "origin_session_id")}
    event.update(type="async_delegation", status="completed", completed_at=20)
    result = {"results": [{"task_index": 0, "summary": "done\x00exact"}]}
    send(5, "delegation.complete", {"event": event, "result": result})
    assert send(6, "delegation.read", {"delegation_id": "d"})["value"]["result"] == result
    assert send(7, "delegation.claim", {"delegation_id": "d", "claim_id": "a"}) == {"value": True}
    assert send(8, "delegation.claim", {"delegation_id": "d", "claim_id": "b"}) == {"value": False}
    assert send(9, "delegation.ack", {"delegation_id": "d", "claim_id": "b"}) == {"value": False}
    assert send(10, "delegation.defer", {"delegation_id": "d", "claim_id": "a"}) == {"value": True}
    assert send(11, "delegation.claim", {"delegation_id": "d", "claim_id": "b"}) == {"value": True}
    assert send(12, "delegation.ack", {"delegation_id": "d", "claim_id": "b"}) == {"value": True}
    row = send(13, "delegation.read", {"delegation_id": "d"})["value"]
    assert row["delivery_state"] == "delivered" and row["delivery_attempts"] == 1


def test_delegation_cannot_forge_parent_route_and_unscheduled_retries_are_once(store, runtime):
    send = _ledger(store, runtime)
    payload = _dispatch()
    with pytest.raises(RuntimeStoreError) as error:
        send(1, "delegation.dispatch", payload | {"parent_session_id": "other"})
    assert error.value.reason == "permission_denied"
    send(1, "delegation.dispatch", payload)
    send(2, "delegation.unscheduled", {"delegation_id": "d"})
    assert send(2, "delegation.unscheduled", {"delegation_id": "d"}) == {"value": None}
    with pytest.raises(RuntimeStoreError) as error:
        send(3, "delegation.read", {"delegation_id": "d"})
    assert error.value.reason == "not_found"
