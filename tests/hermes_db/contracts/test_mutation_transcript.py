"""Canonical branch, reset and rewind publish one exact retryable result."""

import pytest

from hermes_state_runtime import RuntimeStoreError
from tests.hermes_db.contracts.test_prepared_mutations import local_setup


def _args(store, epoch, sid, operation, payload):
    row = store.get_session(sid)
    return dict(epoch=epoch, principal_id="human", session_id=sid, request_id=operation,
        expected_revision=row["runtime_revision"], expected_generation=row["runtime_generation"], operation=operation, payload=payload)


def test_branch_boundary_keeps_tool_answers_and_forks_policy_and_root(store, runtime):
    sid, _ = local_setup(store)
    store.set_session_title(sid, "Parent")
    store.set_session_pinned(sid, True)
    for role, text, extra in [("user", "ask\x00", {}), ("assistant", None, {"tool_calls": [{"id": "tc", "type": "function", "function": {"name": "tool", "arguments": "{}"}}]}),
                              ("tool", "answer", {"tool_call_id": "tc"}), ("user", "excluded", {})]:
        store.append_message(sid, role, text, **extra)
    held = store.get_messages(sid)
    epoch = runtime.begin_epoch(instance_id="owner")
    args = _args(store, epoch, sid, "branch", {"through_message_id": held[1]["id"]})
    result = runtime.mutate_session(**args)
    child = result["branched_session_id"]
    assert result["copied_messages"] == 3
    copied = store.get_messages(child)
    assert [(m["role"], m["content"], m.get("message_uid")) for m in copied] == [(m["role"], m["content"], m.get("message_uid")) for m in held[:3]]
    assert store.get_session(child)["system_prompt"] == store.get_session(sid)["system_prompt"]
    assert store.get_session(child)["title"] == "Parent #2" and not store.get_session(child)["pinned"]
    assert store.get_compression_lineage(child) == [child]
    assert runtime.mutate_session(**args) == result


def test_reset_allows_queued_follower_and_replays_without_another_child(store, runtime):
    sid, _ = local_setup(store)
    store.append_message(sid, "user", "old")
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="human", session_id=sid, request_id="queued", payload={"text": "later"})
    args = _args(store, epoch, sid, "reset", {})
    result = runtime.mutate_session(**args)
    child = result["target_session_id"]
    assert store.get_session(sid)["end_reason"] == "session_reset"
    assert store.get_session(child)["_reset_from"] == sid and store.get_messages(child) == []
    assert store.get_compression_lineage(child) == [child]
    claimed = runtime.claim_input(epoch=epoch, session_id=sid)
    assert claimed["target_session_id"] == sid and claimed["status"] == "started"
    import json
    routed = store.load_gateway_routing_entries()
    assert any(json.loads(raw)["session_id"] == child for raw in routed.values())
    assert runtime.mutate_session(**args) == result


def test_rewind_reports_typed_ask_and_exact_receipt_after_later_append(store, runtime):
    sid, _ = local_setup(store)
    store.append_message(sid, "user", "before")
    target = store.append_message(sid, "user", "retry\x00ask")
    store.append_message(sid, "assistant", "removed")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = _args(store, epoch, sid, "rewind", {"target_message_id": target})
    result = runtime.mutate_session(**args)
    assert result["rewound_count"] == 2 and result["target_message"]["content"] == "retry\x00ask"
    assert [m["content"] for m in store.get_messages(sid)] == ["before"]
    store.append_message(sid, "user", "later")
    assert runtime.mutate_session(**args) == result


def test_branch_refuses_archived_boundary_without_publishing_child(store, runtime):
    sid, _ = local_setup(store)
    target = store.append_message(sid, "user", "archived")
    store.rewind_to_message(sid, target)
    epoch = runtime.begin_epoch(instance_id="owner")
    args = _args(store, epoch, sid, "branch", {"through_message_id": target})
    with pytest.raises(RuntimeStoreError, match="invalid_params"):
        runtime.mutate_session(**args)


@pytest.mark.parametrize("in_place", [True, False])
def test_prepared_compression_changes_target_once_and_keeps_archived_history(store, runtime, in_place):
    sid, _ = local_setup(store)
    store.append_message(sid, "user", "old\x00ask")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = _args(store, epoch, sid, "compress", {})
    snapshot = runtime.mutate_session(**args, _prepare_only=True)["snapshot"]
    prepared = dict(snapshot=snapshot, in_place=in_place,
        messages=[{"role": "user", "content": "summary\x00", "_compressed_summary": True}], summary="summary\x00")
    result = runtime.mutate_session(**args, _prepared=prepared)
    target = result["target_session_id"]
    assert (target == sid) is in_place
    assert result["execution_generation"] == args["expected_generation"] + 1
    assert store.get_messages(target)[0]["content"] == "summary\x00"
    assert store.get_messages(sid, include_inactive=True)[0]["content"] == "old\x00ask"
    store.append_message(target, "user", "after")
    assert runtime.mutate_session(**args, _prepared={}) == result


def test_prepare_commit_detects_changed_physical_target_revision(store, runtime):
    sid, _ = local_setup(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    reset = runtime.mutate_session(**_args(store, epoch, sid, "reset", {}))
    args = _args(store, epoch, sid, "model", {"model": "new", "provider": "provider"})
    snapshot = runtime.mutate_session(**args, _prepare_only=True)["snapshot"]
    runtime.mutate_session(**_args(store, epoch, reset["target_session_id"], "rename", {"title": "late physical change"}))
    with pytest.raises(RuntimeStoreError, match="revision_conflict"):
        runtime.mutate_session(**args, _prepared={"snapshot": snapshot, "policy": snapshot["receipt"]["policy"]})
