"""Closed worker constructor/metadata operations preserve prompt and row ownership."""

import json

import pytest

from hermes_state_runtime import RuntimeStoreError


def _worker(store, runtime):
    store.create_session("s", "cli", system_prompt="original\x00prompt")
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(epoch=epoch, execution_id="worker", session_id="s", generation=0)
    runtime.register_worker(**assignment, kind="compute", adoption_secret="private-test")
    sequence = 0

    def call(operation, payload):
        nonlocal sequence
        value = runtime.mutate_worker(**assignment, sequence=sequence + 1, operation=operation, payload=payload)
        sequence += 1
        return value
    return call


def test_worker_constructor_prompt_pin_and_sidecar_allowlist(store, runtime):
    call = _worker(store, runtime)
    assert call("session.create", {"source": "cli", "model": "model", "model_config": {"max_tokens": 123},
                                   "system_prompt": "must not replace"}) == {"value": "s"}
    row = store.get_session("s")
    assert row["system_prompt"] == "original\x00prompt" and json.loads(row["model_config"])["max_tokens"] == 123
    with pytest.raises(RuntimeStoreError) as error:
        call("session.create", {"source": "cli", "session_key": "foreign"})
    assert error.value.reason == "permission_denied"
    call("session.sidecars", {"patch": {"_usage_anchor": 100}})
    with pytest.raises(RuntimeStoreError) as error:
        call("session.sidecars", {"patch": {"_delegate_from": "foreign"}})
    assert error.value.reason == "invalid_params"
    pin = {"version": "1", "tools": [{"name": "tool", "description": "text\x00"}]}
    call("session.tools", {"tool_names": pin})
    assert json.loads(store.get_session("s")["tool_names"]) == pin
    call("session.prompt", {"system_prompt": "explicit\x00replacement"})
    assert call("session.context", {})["session"]["system_prompt"] == "explicit\x00replacement"


def test_worker_title_conflict_receipt_authorizes_later_numbering(store, runtime):
    store.create_session("other", "cli")
    store.set_session_title("other", "Taken")
    call = _worker(store, runtime)
    refused = call("session.title", {"title": "Taken", "source": "user"})
    assert refused["value"] is False and refused["title_candidate"] == "Taken"
    call("usage.main", {"input_tokens": 1, "api_call_count": 1})
    assert call("session.next_title", {"base_title": "Taken"}) == {"value": "Taken #2"}
    assert call("session.title", {"title": "Taken #2", "source": "user"}) == {"value": True}
    with pytest.raises(RuntimeStoreError) as error:
        call("session.next_title", {"base_title": "unrelated"})
    assert error.value.reason == "permission_denied"


def test_worker_row_sidecars_usage_and_lifecycle_stay_on_owned_transcript(store, runtime):
    call = _worker(store, runtime)
    row_id = call("transcript.append", {"messages": [{"role": "user", "content": "ask"}]})["annotations"][0]["_row_id"]
    assert call("session.message_api_content", {"row_id": row_id, "content": "ask", "api_content": "exact\x00"}) == {"value": 1}
    assert store.get_messages("s")[0]["api_content"] == "exact\x00"
    call("session.user_content", {"row_id": row_id, "content": "expanded", "display_metadata": {"kind": "input"}})
    assert store.get_messages("s")[0]["api_content"] is None
    assert call("session.tail_role", {}) == {"value": "user"}
    assert call("session.row_role", {"row_id": row_id}) == {"value": "user"}
    call("usage.main", {"input_tokens": 5, "output_tokens": 2, "api_call_count": 1, "model": "m", "billing_provider": "p"})
    call("usage.auxiliary", {"task": "title", "input_tokens": 3, "model": "small"})
    assert store.get_session("s")["input_tokens"] == 5
    assert store.auxiliary_usage_by_task("s")["title"]["input_tokens"] == 3
    call("session.billing_route", {"provider": "next", "base_url": None, "billing_mode": None})
    assert store.get_session("s")["system_prompt"] == "original\x00prompt"
    assert call("session.lifecycle", {})["value"]
    call("session.end", {"end_reason": "agent_close"})
    assert store.get_session("s")["end_reason"] == "agent_close"


def test_worker_turn_lease_holder_fences_transcript_writes(store, runtime):
    from hermes_state_errors import SessionTurnLeaseLostError

    call = _worker(store, runtime)
    assert call("turn.acquire", {"holder": "one", "ttl_seconds": 300}) == {"value": True}
    assert call("turn.acquire", {"holder": "two", "ttl_seconds": 300}) == {"value": False}
    assert call("turn.renew", {"holder": "one", "ttl_seconds": 300}) == {"value": True}
    assert call("turn.release", {"holder": "one"}) == {"value": None}
    assert call("turn.acquire", {"holder": "two", "ttl_seconds": 300}) == {"value": True}
    with pytest.raises(SessionTurnLeaseLostError):
        call("transcript.append", {"messages": [{"role": "user", "content": "stale"}], "turn_lease_holder": "one"})
    assert call("transcript.append", {"messages": [{"role": "user", "content": "current"}], "turn_lease_holder": "two"})["count"] == 1
    assert [row["content"] for row in store.get_messages("s")] == ["current"]
