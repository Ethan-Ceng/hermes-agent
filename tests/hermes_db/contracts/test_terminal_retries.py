"""Private retired evidence retains replay output, never executable history."""

import pytest

from hermes_state_runtime import RuntimeStoreError, admission_fingerprint


def _terminal(store, runtime, name, **kwargs):
    from hermes_state import SessionDB
    if isinstance(store, SessionDB):
        import hermes_state_terminal
        return getattr(hermes_state_terminal, name)(store, **kwargs)
    return getattr(runtime, name)(**kwargs)


def test_private_terminal_retry_requires_original_identity_digest_and_epoch(store, runtime):
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="api", session_id="s", request_id="key", payload={"text": "ask\x00"})
    accepted = runtime.admit_input(**args)
    claimed = runtime.claim_input(epoch=epoch, session_id="s")
    runtime.settle_input(epoch=epoch, admission_id=accepted["admission_id"], generation=claimed["generation"], outcome="completed",
        result={"result": {"final_response": "reply\x00", "messages": [{"role": "user", "content": "ask\x00"}, {"role": "assistant", "content": "reply\x00"}], "tools": ["schema"]}, "usage": {"tokens": 7}})
    store.delete_session("s")
    row = _terminal(store, runtime, "retry_terminal_admission", **args)
    assert row["admission_id"] == accepted["admission_id"] and row["payload"] == {} and row["outcome"] == "completed"
    for changed, reason in [({"principal_id": "foreign"}, "not_found"), ({"payload": {"text": "different"}}, "admission_conflict"), ({"epoch": epoch + 1}, "stale_epoch")]:
        with pytest.raises(RuntimeStoreError, match=reason):
            _terminal(store, runtime, "retry_terminal_admission", **(args | changed))
    from hermes_state import SessionDB
    from hermes_db.domains.runtime.receipts import RESULT_PREFIX, load_result
    saved = load_result(store.get_meta(RESULT_PREFIX + accepted["admission_id"])) if isinstance(store, SessionDB) else runtime.admission_result(accepted["admission_id"])
    assert saved == {"result": {"final_response": "reply\x00", "messages": [], "_messages_are_turn_suffix": True}, "usage": {"tokens": 7}}


def test_private_terminal_worker_proof_cannot_read_erased_transcript_receipt(store, runtime):
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(epoch=epoch, **assignment, kind="compute", adoption_secret="private-test")
    args = dict(epoch=epoch, **assignment, sequence=1, operation="transcript.append", payload={"messages": [{"role": "assistant", "content": "private"}]})
    runtime.mutate_worker(**args)
    finish = args | {"sequence": 2, "operation": "execution.finish", "payload": {}}
    runtime.mutate_worker(**finish)
    store.delete_session("s")
    digest = admission_fingerprint(canonical_target="s", payload={"operation": "execution.finish", "payload": {}})
    proof = dict(**assignment, sequence=2, adoption_secret="private-test", payload_digest=digest)
    assert _terminal(store, runtime, "terminal_worker_receipt", **proof) == {"status": "terminal"}
    for changed, reason in [({"adoption_secret": "wrong"}, "permission_denied"), ({"generation": 1}, "stale_generation"), ({"payload_digest": "wrong"}, "admission_conflict"), ({"sequence": 1}, "admission_conflict")]:
        with pytest.raises(RuntimeStoreError, match=reason):
            _terminal(store, runtime, "terminal_worker_receipt", **(proof | changed))
    erased_digest = admission_fingerprint(canonical_target="s", payload={"operation": "transcript.append", "payload": args["payload"]})
    with pytest.raises(RuntimeStoreError, match="stale_generation"):
        _terminal(store, runtime, "terminal_worker_receipt", **(proof | {"sequence": 1, "payload_digest": erased_digest}))
