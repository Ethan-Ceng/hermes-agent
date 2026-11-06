"""Private managed-worker edges use the selected transactional storage capabilities."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_owner_reserves_adopts_persists_and_fences_worker_with_child(store, runtime, monkeypatch):
    from gateway.session_admission import admission_fingerprint
    from gateway.session_contract import SessionRef
    from gateway.session_worker import worker_request
    from gateway.session_worker_reservation import lose_admission_worker, reserve_admission_worker
    from hermes_db.health import profile_home_for_store
    from hermes_state_runtime import RuntimeStoreError
    store.create_session("owned", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="producer", session_id="owned", request_id="r", payload={"text": "ask"})
    started = runtime.claim_input(epoch=epoch, session_id="owned")
    home = profile_home_for_store(store)
    owner = SimpleNamespace(db=store, epoch=epoch, profile_id=str(home), _require_admission_open=lambda: None)
    # OS identity is verified before these database operations; this contract
    # pins that external proof so it can exercise both storage implementations.
    monkeypatch.setattr("gateway.session_worker_reservation.verify_worker_identity", lambda *args: (123, 42.0))
    scope = reserve_admission_worker(owner, admission_id=started["admission_id"], process=None,
        hello={}, principal_id="producer", worker_subject="worker-principal")
    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        reserve_admission_worker(owner, admission_id=started["admission_id"], process=None,
            hello={}, principal_id="producer", worker_subject="worker-principal")
    claim = admission_fingerprint(canonical_target="owned", payload={key: value for key, value in scope.items()
        if key != "epoch"} | {"principal": "worker-principal"})
    monkeypatch.setattr("gateway.session_worker._claim", lambda *args: claim)
    monkeypatch.setattr("gateway.session_worker_child.delegation_limits", lambda *args: (1, 1))
    connection = SimpleNamespace(authority=owner, actor=SimpleNamespace(
        subject="worker-principal", profile_id=str(home), capabilities=frozenset({"worker:adopt"})))
    ref = SessionRef(str(home), "owned")
    adopted = await worker_request(connection, ref, {key: value for key, value in scope.items() if key != "epoch"}, operation="adopt")
    assert adopted["status"] == "running"
    appended = await worker_request(connection, ref, scope | {"sequence": 1, "operation": "transcript.append",
        "payload": {"messages": [{"role": "user", "content": "worker text"}], "turn_lease_holder": None}}, operation="persist")
    assert appended["count"] == 1
    args = scope | {"sequence": 2, "operation": "child.reserve", "payload": {"secret": "child-private-proof"}}
    child = await worker_request(connection, ref, args, operation="persist")
    assert await worker_request(connection, ref, args, operation="persist") == child
    assert store.get_session(child["child"]["session_id"])["parent_session_id"] == "owned"
    refused = await worker_request(connection, ref, args | {"sequence": 3}, operation="persist")
    assert refused == {"refused": "delegation_capacity"}
    lose_admission_worker(owner, started, scope)
    assert runtime.get_admission(admission_id=started["admission_id"])["status"] == "unknown"
    with pytest.raises(RuntimeStoreError, match="stale_generation"):
        await worker_request(connection, ref, scope | {"sequence": 4, "operation": "session.title",
            "payload": {"title": "late"}}, operation="persist")
