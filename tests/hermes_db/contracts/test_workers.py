"""Owner-RPC worker identity, ordered receipts and adoption contracts."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_worker_receipts_fence_assignment_sequence_and_duplicate_effects(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(execution_id="worker", session_id="s", generation=0)
    row = runtime.register_worker(epoch=epoch, **assignment, kind="compute", adoption_secret="private-test")
    assert row["status"] == "registered" and "adoption_digest" not in row
    args = dict(epoch=epoch, **assignment, sequence=1, operation="transcript.append",
                payload={"messages": [{"role": "assistant", "content": "once"}]})
    result = runtime.mutate_worker(**args)
    assert runtime.mutate_worker(**args) == result and store.message_count("s") == 1
    assert result["count"] == 1 and result["annotations"][0]["message_uid"]
    for change, reason in [({"sequence": 3}, "invalid_params"),
                           ({"session_id": "other"}, "permission_denied"),
                           ({"generation": 1}, "stale_generation"),
                           ({"payload": {"messages": [{"role": "assistant", "content": "changed"}]}}, "admission_conflict")]:
        with pytest.raises(RuntimeStoreError) as error:
            runtime.mutate_worker(**(args | change))
        assert error.value.reason == reason
    usage = args | {"sequence": 2, "operation": "usage.main", "payload": {"input_tokens": 7, "api_call_count": 1}}
    runtime.mutate_worker(**usage)
    runtime.mutate_worker(**usage)
    assert store.get_session("s")["input_tokens"] == 7 and store.get_session("s")["api_call_count"] == 1
    finish = args | {"sequence": 3, "operation": "execution.finish", "payload": {}}
    assert runtime.mutate_worker(**finish) == {"status": "terminal"}
    assert runtime.mutate_worker(**finish) == {"status": "terminal"}
    assert runtime.mutate_worker(**args) == result
    with pytest.raises(RuntimeStoreError) as error:
        runtime.mutate_worker(**(args | {"sequence": 4}))
    assert error.value.reason == "stale_generation"
    runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="new", payload={})
    assert runtime.claim_input(epoch=epoch, session_id="s")["generation"] == 1
    with pytest.raises(RuntimeStoreError) as error:
        runtime.mutate_worker(**args)
    assert error.value.reason == "stale_generation"


def test_worker_restart_requires_private_adoption_and_preserves_receipts(store, runtime):
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(epoch=epoch, **assignment, kind="compute", adoption_secret="private-test")
    args = dict(epoch=epoch, **assignment, sequence=1, operation="transcript.append",
                payload={"messages": [{"role": "assistant", "content": "once"}]})
    result = runtime.mutate_worker(**args)
    fresh = runtime.begin_epoch(instance_id="replacement")
    runtime.recover_inputs(epoch=fresh)
    with pytest.raises(RuntimeStoreError) as error:
        runtime.mutate_worker(**(args | {"epoch": fresh}))
    assert error.value.reason == "stale_epoch"
    with pytest.raises(RuntimeStoreError) as error:
        runtime.adopt_worker(epoch=fresh, **assignment, adoption_secret="wrong")
    assert error.value.reason == "permission_denied"
    row = runtime.adopt_worker(epoch=fresh, **assignment, adoption_secret="private-test")
    assert row["owner_epoch"] == fresh and row["status"] == "running"
    assert runtime.mutate_worker(**(args | {"epoch": fresh})) == result
    assert store.message_count("s") == 1


def test_worker_context_reads_keep_revision_and_are_retired_at_finish(store, runtime):
    store.create_session("s", "test", system_prompt="exact\x00prompt")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(epoch=epoch, **assignment, kind="compute", adoption_secret="private-test")
    before = store.get_session("s")["runtime_revision"]
    read = dict(epoch=epoch, **assignment, sequence=1, operation="session.context", payload={})
    assert runtime.mutate_worker(**read)["session"]["system_prompt"] == "exact\x00prompt"
    assert store.get_session("s")["runtime_revision"] == before
    runtime.mutate_worker(epoch=epoch, **assignment, sequence=2, operation="execution.finish", payload={})
    with pytest.raises(RuntimeStoreError) as error:
        runtime.mutate_worker(**read)
    assert error.value.reason == "stale_generation"
