"""Canonical execution admission contracts independent of SQL syntax."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_request_retry_payload_conflict_fifo_and_generation(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="one", payload={"text": "hello"})
    first = runtime.admit_input(**args)
    assert runtime.admit_input(**args) == first
    with pytest.raises(RuntimeStoreError) as error:
        runtime.admit_input(**(args | {"payload": {"text": "changed"}}))
    assert error.value.reason == "admission_conflict" and error.value.field == "request_id"
    second = runtime.admit_input(**(args | {"request_id": "two"}))
    assert first["seq"] < second["seq"]
    assert runtime.claim_input(epoch=epoch, session_id="s", head=second["admission_id"]) is False
    claimed = runtime.claim_input(epoch=epoch, session_id="s")
    assert claimed["admission_id"] == first["admission_id"] and claimed["generation"] == 1
    assert runtime.claim_input(epoch=epoch, session_id="s") is None
    with pytest.raises(RuntimeStoreError) as error:
        runtime.settle_input(epoch=epoch, admission_id=first["admission_id"], generation=2, outcome="completed")
    assert error.value.reason == "stale_generation"
    runtime.settle_input(epoch=epoch, admission_id=first["admission_id"], generation=1, outcome="completed")
    claimed = runtime.claim_input(epoch=epoch, session_id="s")
    assert claimed["admission_id"] == second["admission_id"] and claimed["generation"] == 2


def test_restart_never_replays_started_work_and_fences_old_epoch(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    args = dict(epoch=epoch, principal_id="human", session_id="s", payload={"text": "hello"})
    first = runtime.admit_input(**args, request_id="one")
    runtime.admit_input(**args, request_id="two")
    runtime.claim_input(epoch=epoch, session_id="s")
    fresh = runtime.begin_epoch(instance_id="replacement")
    assert fresh > epoch and runtime.recover_inputs(epoch=fresh) == 1
    assert runtime.recover_inputs(epoch=fresh) == 0
    assert runtime.get_admission(admission_id=first["admission_id"])["status"] == "unknown"
    store.create_session("new", "test")
    assert runtime.rehome_inputs(epoch=fresh, old_session_id="s", new_session_id="new", principal_prefix="human") == []
    with pytest.raises(RuntimeStoreError) as error:
        runtime.claim_input(epoch=fresh, session_id="s")
    assert error.value.reason == "unknown_execution"
    with pytest.raises(RuntimeStoreError) as error:
        runtime.claim_input(epoch=epoch, session_id="s")
    assert error.value.reason == "stale_epoch"


def test_queue_cap_cancellation_and_exact_retry_are_consistent(store, runtime):
    from hermes_state_runtime import ADMISSION_QUEUE_MAX
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    args = dict(epoch=epoch, principal_id="human", session_id="s", payload={"text": "same"})
    rows = [runtime.admit_input(**args, request_id=str(index)) for index in range(ADMISSION_QUEUE_MAX)]
    assert runtime.admit_input(**args, request_id="0") == rows[0]
    with pytest.raises(RuntimeStoreError) as error:
        runtime.admit_input(**args, request_id="over")
    assert error.value.reason == "queue_full"
    assert runtime.cancel_input(epoch=epoch, admission_id=rows[0]["admission_id"])["outcome"] == "cancelled"
    assert runtime.admit_input(**args, request_id="over")["status"] == "queued"
    assert len(runtime.list_admissions(session_id="s")) == ADMISSION_QUEUE_MAX


def test_steer_revert_and_terminal_transfer_are_once_only(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    args = dict(epoch=epoch, principal_id="human", session_id="s", payload={"text": "same"})
    first = runtime.admit_input(**args, request_id="one")
    second = runtime.admit_input(**args, request_id="two")
    runtime.claim_input(epoch=epoch, session_id="s")
    transfer = dict(epoch=epoch, admission_id=second["admission_id"], generation=1)
    with pytest.raises(RuntimeStoreError) as error:
        runtime.steer_input(**(transfer | {"generation": True}))
    assert error.value.reason == "session_idle"
    row, delivered = runtime.steer_input(**transfer)
    assert row["outcome"] == "steering" and delivered
    assert runtime.steer_input(**transfer) == (row, False)
    assert runtime.revert_steer(**transfer) and not runtime.revert_steer(**transfer)
    runtime.steer_input(**transfer)
    runtime.settle_input(epoch=epoch, admission_id=first["admission_id"], generation=1, outcome="completed",
                          _transfers={second["admission_id"]: True})
    assert runtime.get_admission(admission_id=second["admission_id"])["outcome"] == "steered"
    assert not runtime.revert_steer(**transfer)


def test_unknown_resolution_requires_explicit_generation_and_never_requeues(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    first = runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="one", payload={"text": "ask"})
    runtime.claim_input(epoch=epoch, session_id="s")
    fresh = runtime.begin_epoch(instance_id="replacement")
    runtime.recover_inputs(epoch=fresh)
    args = dict(epoch=fresh, admission_id=first["admission_id"], generation=1)
    row = runtime.resolve_unknown(**args)
    assert row["status"] == "terminal" and row["outcome"] == "interrupted"
    assert runtime.resolve_unknown(**args) == row
    assert runtime.claim_input(epoch=fresh, session_id="s") is None


def test_rehome_and_automation_retarget_keep_fifo_and_identity(store, runtime):
    for target in ("old", "new"):
        store.create_session(target, "test")
    epoch = runtime.begin_epoch(instance_id="boot")
    args = dict(epoch=epoch, principal_id="human:one", session_id="old", request_id="r", payload={"text": "ask"})
    row = runtime.admit_input(**args)
    assert runtime.rehome_inputs(epoch=epoch, old_session_id="old", new_session_id="new", principal_prefix="human:") == [row["admission_id"]]
    moved = runtime.admit_input(**(args | {"session_id": "new"}))
    assert moved["seq"] == row["seq"] and moved["admission_id"] == row["admission_id"]
    assert runtime.list_admissions(session_id="old") == []
    assert runtime.rehome_inputs(epoch=epoch, old_session_id="missing", new_session_id="new", principal_prefix="human:") == []
    payload = {"local_automation_v1": {"target": "old"}}
    row = runtime.admit_input(epoch=epoch, principal_id="human", session_id="old", request_id="auto", payload=payload)
    assert runtime.retarget_automation(epoch=epoch, session_id="old", principal_id="human", old_targets=["old"], new_target="new") == [row["admission_id"]]
    replay = runtime.admit_input(epoch=epoch, principal_id="human", session_id="old", request_id="auto",
        payload={"local_automation_v1": {"target": "new"}})
    assert replay["seq"] == row["seq"] and replay["admission_id"] == row["admission_id"]
