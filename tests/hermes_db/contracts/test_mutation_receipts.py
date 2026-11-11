"""Canonical session edits share the revision-fenced exact-retry transaction."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_metadata_mutation_receipt_replays_before_revision_and_rejects_different_request(store, runtime):
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="rename",
        expected_revision=store.get_session("s")["runtime_revision"], operation="rename", payload={"title": " New title "})
    result = runtime.mutate_session(**args)
    assert result["title"] == "New title" and result["revision"] == args["expected_revision"] + 1
    assert runtime.mutate_session(**args) == result
    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        runtime.mutate_session(**(args | {"payload": {"title": "Other"}}))
    with pytest.raises(RuntimeStoreError, match="revision_conflict"):
        runtime.mutate_session(**(args | {"request_id": "another"}))
    sidebar = args | {"request_id": "sidebar", "expected_revision": result["revision"], "operation": "sidebar",
                      "payload": {"pinned": True, "unread": True}}
    saved = runtime.mutate_session(**sidebar)
    assert saved["pinned"] and store.get_session("s")["pinned"]
    assert runtime.mutate_session(**sidebar) == saved


def test_delete_mutation_refuses_live_lease_and_replays_after_row_disappears(store, runtime):
    from hermes_state_errors import SessionCompressionInProgressError
    from hermes_state_mutation_guards import busy_refusal
    store.create_session("s", "cli")
    store.append_message("s", "user", "history")
    epoch = runtime.begin_epoch(instance_id="owner")
    snapshot = store.get_session("s")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="delete", operation="delete", payload={},
        expected_revision=snapshot["runtime_revision"], expected_generation=snapshot["runtime_generation"])
    assert store.try_acquire_compression_lock("s", "holder")
    with pytest.raises((RuntimeStoreError, SessionCompressionInProgressError)) as error:
        runtime.mutate_session(**args)
    refusal = busy_refusal(error.value) if isinstance(error.value, SessionCompressionInProgressError) else error.value
    assert refusal.reason == "session_busy" and refusal.field == "compression"
    store.release_compression_lock("s", "holder")
    result = runtime.mutate_session(**args)
    assert result["deleted_ids"] == ["s"] and store.get_session("s") is None
    assert runtime.mutate_session(**args) == result
    with pytest.raises(RuntimeStoreError, match="not_found"):
        runtime.mutate_session(**(args | {"request_id": "different"}))


def test_core_mutation_receipt_failure_rolls_back_title_and_revision(core_pair, monkeypatch):
    from hermes_cli.db_runtime import create_runtime_store
    from hermes_db.domains.sessions.postgres.operations import mutations

    store, _ = core_pair
    store.create_session("s", "cli")
    runtime = create_runtime_store(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    before = store.get_session("s")

    def fail(*args):
        raise RuntimeError("receipt unavailable")

    monkeypatch.setattr(mutations, "save_receipt", fail)
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        runtime.mutate_session(epoch=epoch, principal_id="human", session_id="s", request_id="r", operation="rename",
            expected_revision=before["runtime_revision"], payload={"title": "Must roll back"})
    assert store.get_session("s") == before


def test_delete_owner_closure_stops_at_foreign_principal_even_if_later_labels_match(store, runtime):
    store.create_session("root", "telegram", user_id="one", session_key="key", chat_id="chat")
    store.end_session("root", "compression")
    store.create_session("foreign", "telegram", parent_session_id="root", user_id="other")
    store.end_session("foreign", "compression")
    store.create_session("behind", "telegram", parent_session_id="foreign", user_id="one")
    epoch = runtime.begin_epoch(instance_id="owner")
    row = store.get_session("root")
    result = runtime.mutate_session(epoch=epoch, principal_id="one", session_id="root", request_id="delete", operation="delete",
        payload={}, expected_revision=row["runtime_revision"], expected_generation=row["runtime_generation"])
    assert result["deleted_ids"] == ["root"]
    assert store.get_session("foreign") is not None and store.get_session("behind") is not None
