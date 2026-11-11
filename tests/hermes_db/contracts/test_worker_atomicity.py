"""Receipt failure and delegated-child retirement are atomic and scope-bound."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def _registered(store):
    from hermes_cli.db_runtime import create_runtime_store
    store.create_session("s", "cli")
    runtime = create_runtime_store(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(epoch=epoch, execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(**assignment, kind="compute", adoption_secret="private-test")
    return runtime, assignment


def test_receipt_failure_rolls_back_transcript_counters_and_sequence(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.operations import workers
    store = core_pair[0]
    runtime, assignment = _registered(store)
    args = dict(**assignment, sequence=1, operation="transcript.append",
                payload={"messages": [{"role": "assistant", "content": "once"}]})

    def refuse_receipt(*unused):
        raise RuntimeError("receipt rejected")

    with monkeypatch.context() as patch:
        patch.setattr(workers, "_save_receipt", refuse_receipt)
        with pytest.raises(RuntimeError, match="receipt rejected"):
            runtime.mutate_worker(**args)
    assert store.message_count("s") == 0 and store.get_session("s")["message_count"] == 0
    result = runtime.mutate_worker(**args)
    assert result["count"] == 1 and runtime.mutate_worker(**args) == result
    assert store.message_count("s") == 1


def test_child_reservation_capacity_and_parent_finish_close_children(core_pair):
    from hermes_db.domains.runtime.postgres.operations.worker_children import reservation_effect
    store = core_pair[0]
    runtime, assignment = _registered(store)
    handlers = {"child.reserve": reservation_effect(epoch=assignment["epoch"], execution_id="worker",
        identity={"profile_id": "profile", "pid": 1, "birth": 1}, principal="human", limits=(1, 1))}
    args = dict(**assignment, sequence=1, operation="child.reserve", payload={"secret": "private-child-key"}, handlers=handlers)
    child = runtime.apply_worker_receipt(**args)["child"]
    assert runtime.apply_worker_receipt(**args)["child"] == child
    assert store.get_session(child["session_id"])["parent_session_id"] == "s"
    assert runtime.apply_worker_receipt(**(args | {"sequence": 2})) == {"refused": "delegation_capacity"}
    runtime.mutate_worker(**assignment, sequence=3, operation="execution.finish", payload={})
    assert store.get_session(child["session_id"])["end_reason"] == "agent_close"
    with pytest.raises(RuntimeStoreError) as error:
        runtime.mutate_worker(epoch=assignment["epoch"], **child, sequence=1, operation="session.context", payload={})
    assert error.value.reason == "stale_generation"


def test_worker_ids_and_receipts_do_not_cross_stores(core_pair):
    rows = [_registered(store) for store in core_pair]
    for index, (runtime, assignment) in enumerate(rows):
        result = runtime.mutate_worker(**assignment, sequence=1, operation="transcript.append",
            payload={"messages": [{"role": "assistant", "content": str(index)}]})
        assert result["count"] == 1
    assert core_pair[0].get_messages("s")[0]["content"] == "0"
    assert core_pair[1].get_messages("s")[0]["content"] == "1"
