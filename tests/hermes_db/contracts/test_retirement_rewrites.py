"""Destructive retirement preserves fences and exact terminal identities."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_native_delete_retires_id_and_orphans_independent_conversations(store):
    store.create_session("root", "cli")
    store.append_message("root", "user", "root history")
    store.create_session("delegate", "delegate", parent_session_id="root", model_config={"_delegate_from": "root"})
    store.end_session("root", "compression")
    store.create_session("child", "cli", parent_session_id="root")
    store.append_message("child", "user", "continuation")
    store.create_session("branch", "cli", parent_session_id="root", model_config={"_branched_from": "root"})
    assert store.delete_session("root")
    assert store.get_session("root") is None and store.get_session("delegate") is None
    assert store.get_session("branch")["parent_session_id"] is None
    assert store.get_session("child")["parent_session_id"] is None
    assert store.get_compression_lineage("child") == ["child"]
    assert store.get_messages("child")[0]["content"] == "continuation"
    with pytest.raises(RuntimeStoreError, match="not_found"):
        store.ensure_session("root", source="unknown")


def test_chain_delete_skips_whole_selected_conversation_when_a_segment_is_leased(store):
    store.create_session("root", "cli")
    store.end_session("root", "compression")
    store.create_session("child", "cli", parent_session_id="root")
    assert store.try_acquire_session_turn_lease("child", "holder")
    skipped = []
    assert store.delete_sessions(["root"], include_compression_chain=True, exclude_active_write_guards=True,
                                 skipped_ids=skipped) == 0
    assert skipped == ["root"]
    store.release_session_turn_lease("child", "holder")
    assert store.delete_sessions(["child"], include_compression_chain=True) == 1
    assert store.get_session("root") is None and store.get_session("child") is None


def test_delete_refuses_live_ledger_then_keeps_only_terminal_exact_replay(store, runtime):
    store.create_session("s", "cli")
    store.append_message("s", "user", "history\x00")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="once", payload={"text": "input\x00"})
    accepted = runtime.admit_input(**args)
    with pytest.raises(RuntimeStoreError, match="session_busy"):
        store.delete_session("s")
    assert store.get_messages("s")[0]["content"] == "history\x00"
    runtime.cancel_input(epoch=epoch, admission_id=accepted["admission_id"])
    assert store.delete_session("s")
    replay = runtime.admit_input(**args)
    assert replay["admission_id"] == accepted["admission_id"] and replay["status"] == "terminal" and replay["payload"] == {}
    with pytest.raises(RuntimeStoreError, match="not_found"):
        runtime.admit_input(**(args | {"request_id": "new"}))
    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        runtime.admit_input(**(args | {"payload": {"text": "different"}}))


def test_delete_preserves_unknown_execution_for_explicit_resolution(store, runtime):
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="old")
    runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={})
    runtime.claim_input(epoch=epoch, session_id="s")
    epoch = runtime.begin_epoch(instance_id="new")
    runtime.recover_inputs(epoch=epoch)
    with pytest.raises(RuntimeStoreError, match="unknown_execution"):
        store.delete_session("s")
    assert store.get_session("s") is not None
    assert runtime.list_admissions(session_id="s")[0]["status"] == "unknown"


def test_core_delete_same_id_cannot_remove_other_store_rows_or_routes(core_pair):
    first, second = core_pair
    for store in core_pair:
        store.create_session("same", "cli", system_prompt="exact prompt")
        store.append_message("same", "user", "exact history")
        store.save_gateway_routing_entry("route", '{"session_id":"same"}')
    assert first.delete_session("same")
    assert second.get_session("same")["system_prompt"] == "exact prompt"
    assert second.get_messages("same")[0]["content"] == "exact history"
    assert second.load_gateway_routing_entries() == {"route": '{"session_id":"same"}'}


def test_verified_delete_refuses_new_display_rows_or_new_delegate_targets(store):
    store.create_session("s", "cli")
    store.append_message("s", "user", "first")
    snapshot = store.get_messages("s", include_compacted=True)
    store.append_message("s", "assistant", "late")
    assert not store.delete_session("s", expected_delete_ids=["s"], expected_display_messages={"s": snapshot})
    store.create_session("delegate", "delegate", parent_session_id="s", model_config={"_delegate_from": "s"})
    assert not store.delete_session("s", expected_delete_ids=["s"])
    current = store.get_messages("s", include_compacted=True)
    assert store.delete_session("s", expected_delete_ids=["s", "delegate"], expected_display_messages={"s": current})


def test_core_retirement_failure_rolls_back_fences_routes_and_callbacks(core_pair, monkeypatch):
    from hermes_db.domains.sessions.postgres.operations import retirement
    from hermes_db.domains.runtime.postgres.queries import runtime
    from hermes_state_mutation_retirement import RETIRED_PREFIX

    store, _ = core_pair
    store.create_session("s", "cli")
    store.append_message("s", "user", "retained")
    store.save_gateway_routing_entry("route", '{"session_id":"s"}')
    notified = []
    monkeypatch.setattr(store, "_after_session_delete", lambda *args, **kwargs: notified.append(args))

    def fail(*args):
        raise RuntimeError("injected after fence")

    monkeypatch.setattr(retirement, "delete_rows", fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.delete_session("s")
    assert store.get_messages("s")[0]["content"] == "retained" and not notified
    assert store.load_gateway_routing_entries() == {"route": '{"session_id":"s"}'}
    with store._read() as conn:
        assert runtime.meta(conn, store.scope, RETIRED_PREFIX + "s") is None


def test_core_snapshot_cleanup_is_exact_and_cannot_escape_configured_directory(core_pair, tmp_path):
    store, _ = core_pair
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    sid = "safe[1]"
    store.create_session(sid, "cli")
    names = [f"{sid}.json", f"{sid}.jsonl", f"session_{sid}.json", f"request_dump_{sid}_one.json"]
    for name in [*names, "request_dump_safe1_one.json"]:
        (snapshots / name).write_text("cache", encoding="utf-8")
    assert store.delete_session(sid, sessions_dir=snapshots)
    assert not any((snapshots / name).exists() for name in names)
    assert (snapshots / "request_dump_safe1_one.json").exists()
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    store.create_session("../outside", "cli")
    assert store.delete_session("../outside", sessions_dir=snapshots)
    assert outside.read_text(encoding="utf-8") == "keep"


def test_physical_parent_delete_keeps_orphaned_conversations_independent(store):
    store.create_session("root", "cli")
    store.end_session("root", "compression")
    for sid in ("one", "two"):
        store.create_session(sid, "cli", parent_session_id="root")
    assert store.delete_session("root")
    store.set_session_pinned("one", True)
    assert not store.get_session("two")["pinned"]
    assert store.try_acquire_session_turn_lease("one", "first")
    assert store.try_acquire_session_turn_lease("two", "second")
