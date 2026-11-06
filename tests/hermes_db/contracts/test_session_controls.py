"""Session control receipts and refresh epochs do not alter cached history."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_prompt_refresh_orders_profile_and_session_requests_without_rewriting_prompt(store):
    store.create_session("one", "cli", system_prompt="exact\x00prefix")
    store.create_session("two", "cli")
    assert store.count_sessions_with_stored_prompt() == 1
    assert store.prompt_refresh_epoch("one") == 0
    first = store.request_prompt_refresh("one")
    assert store.prompt_refresh_epoch("one") == first and store.prompt_refresh_epoch("two") == 0
    whole = store.request_prompt_refresh()
    assert whole > first and store.prompt_refresh_epoch("two") == whole
    assert store.get_session("one")["system_prompt"] == "exact\x00prefix"


def test_chat_pick_receipt_fences_revision_and_replays_after_mount_changes(store, runtime):
    from hermes_state import SessionDB
    from hermes_state_mutation_chat_pick import chat_pick_key, commit_chat_pick, prepare_chat_pick

    store.create_session("s", "telegram")
    epoch = runtime.begin_epoch(instance_id="owner")
    params = {"request_id": "pick", "expected_revision": 0, "expected_generation": 0,
        "operation": "model", "payload": {"model": "chosen"}}
    key, digest = chat_pick_key("human", "s", params)
    args = dict(epoch=epoch, key=key, digest=digest, session_id="s", params=params)
    prepare = lambda **kw: prepare_chat_pick(store, **kw) if isinstance(store, SessionDB) else runtime.prepare_chat_pick(**kw)
    commit = lambda **kw: commit_chat_pick(store, **kw) if isinstance(store, SessionDB) else runtime.commit_chat_pick(**kw)
    assert prepare(**args)["row"]["id"] == "s"
    result = {"session_id": "s", "operation": "model", "model": "chosen", "execution_generation": 0}
    committed = commit(**args, result=result)
    assert committed["revision"] == 1
    runtime.mutate_session(epoch=epoch, principal_id="human", session_id="s", request_id="rename", expected_revision=1,
        operation="rename", payload={"title": "new revision"})
    assert prepare(**args) == {"receipt": committed}
    assert commit(**args, result={}) == committed
    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        prepare(**(args | {"digest": "different"}))


def test_canonical_import_receipt_exists_without_preexisting_session_and_replays_exactly(store, runtime):
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="imported", request_id="import", expected_revision=0,
        operation="import", payload={"sessions": [{"id": "imported", "source": "import", "messages": [{"role": "user", "content": "exact\x00"}]}]})
    result = runtime.mutate_session(**args)
    assert result["imported_ids"] == ["imported"] and result["revision"] == 1
    assert store.get_messages("imported")[0]["content"] == "exact\x00"
    assert runtime.mutate_session(**args) == result
