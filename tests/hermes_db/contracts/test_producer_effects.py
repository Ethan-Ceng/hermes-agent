"""Existing producer rewrites and folds share the selected admission transaction."""

import pytest


def test_automation_fold_refuses_changed_fifo_then_commits_payload_and_cancellation(store, runtime):
    from gateway.session_automation import _fold_queued
    from hermes_state_runtime import RuntimeStoreError
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    old = runtime.admit_input(epoch=epoch, principal_id="automation", session_id="s", request_id="first",
        payload={"text": "first output", "local_automation_v1": {"identities": ["first"]}})
    later = runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="later", payload={"text": "later"})
    replaced = []
    args = dict(epoch=epoch, principal_id="automation", session_id="s", request_id="folded", payload={"text": "batched output"})
    with pytest.raises(RuntimeStoreError, match="stale_generation"):
        runtime.admit_input(**args, _authorize_write=_fold_queued(old["admission_id"], "s", replaced, store=store))
    assert runtime.get_admission(admission_id=old["admission_id"])["payload"]["text"] == "first output"
    assert runtime.find_admission(principal_id="automation", session_id="s", request_id="folded") is None
    effect = _fold_queued(old["admission_id"], "s", replaced, [later["admission_id"]], store=store)
    accepted = runtime.admit_input(**args, _authorize_write=effect)
    folded = runtime.get_admission(admission_id=old["admission_id"])
    assert folded["status"] == "terminal" and folded["outcome"] == "cancelled"
    assert "identities" not in folded["payload"]["local_automation_v1"]
    assert replaced == [old["admission_id"]]
    assert runtime.admit_input(**args, _authorize_write=effect) == accepted


def test_retry_rewrite_stays_unchanged_when_admission_refuses_and_commits_with_acceptance(store, runtime):
    from gateway.session_retry_admission import RetryRewrite, compose
    from hermes_db.integration.runtime_access import effect_for_store
    from hermes_state_runtime import RuntimeStoreError
    store.create_session("s", "cli")
    store.append_message("s", "user", "keep")
    store.append_message("s", "assistant", "remove on accepted retry")
    pinned = store.get_active_message_ids("s")
    epoch = runtime.begin_epoch(instance_id="owner")
    queued = [runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id=str(n), payload={})
        for n in range(32)]

    def replace(conn):
        store.replace_messages_in_transaction(conn, "s", [{"role": "user", "content": "keep"}],
            active_only=True, reject_active_turn_lease=True, expected_active_ids=pinned)

    rewrite = RetryRewrite(db=store, session_id="s", source=object(), on_commit=lambda: None,
        write=effect_for_store(store, replace, lambda conn, scope: replace(conn)))
    gate = effect_for_store(store, lambda conn: None, lambda conn, scope: None)
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="retry", payload={"text": "retry"},
        _authorize_write=compose(rewrite, gate))
    with pytest.raises(RuntimeStoreError, match="queue_full"):
        runtime.admit_input(**args)
    assert not rewrite.applied and len(store.get_messages_as_conversation("s")) == 2
    runtime.cancel_input(epoch=epoch, admission_id=queued[-1]["admission_id"])
    accepted = runtime.admit_input(**args)
    assert rewrite.applied and [row["content"] for row in store.get_messages_as_conversation("s")] == ["keep"]
    assert runtime.admit_input(**args) == accepted
