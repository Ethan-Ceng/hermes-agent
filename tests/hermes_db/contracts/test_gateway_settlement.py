"""Ordinary owner settlement writes its result and transcript boundary together."""

import pytest


def test_failed_live_settlement_marks_unknown_once_and_keeps_fenced_identity(store, runtime):
    from types import SimpleNamespace
    from gateway.session_settlement_recovery import _mark_unknown
    from gateway.session_results import admission_result
    from hermes_state_runtime import RuntimeStoreError
    epoch, row = _started(store, runtime)
    owner = SimpleNamespace(db=store, epoch=epoch, sessions={})
    before = store.get_session("s")["runtime_revision"]
    assert _mark_unknown(owner, row) == "unknown"
    assert _mark_unknown(owner, row) == "unknown"
    assert store.get_session("s")["runtime_revision"] == before + 1
    assert admission_result(store, row["admission_id"]) is None
    runtime.begin_epoch(instance_id="replacement")
    with pytest.raises(RuntimeStoreError, match="stale_epoch"):
        _mark_unknown(owner, row)


def _started(store, runtime):
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={"text": "ask"})
    row = runtime.claim_input(epoch=epoch, session_id="s")
    store.append_message("s", "user", "ask")
    return epoch, row


def test_gateway_result_retry_preserves_committed_reply_and_rejects_wrong_generation(store, runtime):
    from gateway.session_results import finish_result, admission_result
    from hermes_state_runtime import RuntimeStoreError
    epoch, row = _started(store, runtime)
    settled, reply = finish_result(store, epoch=epoch, row=row, response="answer", outcome="completed")
    assert settled["status"] == "terminal" and reply == "answer"
    assert admission_result(store, row["admission_id"])["result"]["final_response"] == "answer"
    assert finish_result(store, epoch=epoch, row=row, response="changed", outcome="failed")[1] == "answer"
    with pytest.raises(RuntimeStoreError, match="stale_generation"):
        finish_result(store, epoch=epoch, row={**row, "generation": row["generation"] + 1}, response="bad", outcome="failed")


def test_unknown_discard_boundary_is_committed_once_with_its_receipt(store, runtime):
    from gateway.session_results import close_discarded_turn
    from hermes_db.domains.runtime.access import effect_for_store
    epoch, row = _started(store, runtime)
    epoch = runtime.begin_epoch(instance_id="replacement")
    runtime.recover_inputs(epoch=epoch)
    args = dict(epoch=epoch, admission_id=row["admission_id"], generation=row["generation"],
        _terminal_write=effect_for_store(store,
            lambda conn, lost: close_discarded_turn(store, conn, lost, "owner stopped"),
            lambda conn, scope, lost: close_discarded_turn(store, conn, lost, "owner stopped")))
    runtime.resolve_unknown(**args)
    runtime.resolve_unknown(**args)
    transcript = store.get_messages_as_conversation("s")
    assert [row["content"] for row in transcript] == ["ask", "owner stopped"]
    assert runtime.get_admission(admission_id=row["admission_id"])["outcome"] == "interrupted"
