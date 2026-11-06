"""Compression publication is one durable lineage handoff, fenced by holder."""

import json
import time

import pytest


def test_publish_keeps_prompt_tools_route_pin_and_late_tail(store):
    store.create_session("parent", "telegram", system_prompt="parent prompt", model_config={"onboarding_run": "yes"},
        user_id="u", session_key="route", chat_id="chat", display_name="Name", cwd="/workspace")
    store.update_session_tool_names("parent", [{"name": "tool"}])
    store.set_session_pinned("parent", True)
    store.append_message("parent", "user", "original", timestamp=1234.0)
    mark = store.get_active_message_watermark("parent")
    store.append_message("parent", "assistant", "late", reasoning="private\x00reason")
    assert store.try_acquire_compression_lock("parent", "compressor")
    messages = [{"role": "user", "content": "original"}]
    store.publish_compression_child(parent_session_id="parent", child_session_id="child", source="telegram",
        messages=messages, system_prompt="child\x00prompt", model_config={"prompt_refresh_epoch": 7},
        compression_lock_holder="compressor", watermark=mark)
    parent, child = store.get_session("parent"), store.get_session("child")
    assert parent["end_reason"] == "compression" and child["ended_at"] is None
    assert child["system_prompt"] == "child\x00prompt"
    for key in ("tool_names", "user_id", "session_key", "chat_id", "display_name", "cwd", "pinned"):
        assert child[key] == parent[key]
    assert json.loads(child["model_config"]) == {"onboarding_run": "yes", "prompt_refresh_epoch": 7}
    rows = store.get_messages("child")
    assert [row["content"] for row in rows] == ["original", "late"]
    assert rows[0]["timestamp"] == 1234.0 and rows[1]["reasoning"] == "private\x00reason"
    assert store.get_compression_chain("parent") == ["parent", "child"]
    assert store.get_compression_tip("parent") == "child"
    assert store.try_acquire_session_turn_lease("parent", "turn-owner")
    assert not store.try_acquire_session_turn_lease("child", "other")


def test_publish_refreshes_expired_unclaimed_lease_inside_commit(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store.create_session("p", "test")
    assert store.try_acquire_compression_lock("p", "owner", ttl_seconds=5)
    clock[0] += 6
    store.publish_compression_child(parent_session_id="p", child_session_id="c", source="test",
        messages=[{"role": "user", "content": "handoff"}], compression_lock_holder="owner",
        require_lease_refresh=True)
    assert store.get_compression_tip("p") == "c"


def test_publish_displaced_owner_or_deliberate_boundary_cannot_create_child(store):
    from hermes_state_errors import CompressionSessionBusyError

    store.create_session("p", "test")
    assert store.try_acquire_compression_lock("p", "new")
    messages = [{"role": "user", "content": "handoff"}]
    with pytest.raises(CompressionSessionBusyError):
        store.publish_compression_child(parent_session_id="p", child_session_id="c", source="test",
            messages=messages, compression_lock_holder="old", require_lease_refresh=True)
    assert store.get_session("c") is None and store.get_session("p")["ended_at"] is None
    assert "_row_id" not in messages[0]
    store.end_session("p", "cli_close")
    with pytest.raises(RuntimeError):
        store.publish_compression_child(parent_session_id="p", child_session_id="c", source="test",
            messages=messages, compression_lock_holder="new")
    assert store.get_session("c") is None and store.get_session("p")["end_reason"] == "cli_close"


def test_publish_allows_stale_automatic_close_and_watermark_ceiling(store):
    store.create_session("p", "test")
    mark = store.get_active_message_watermark("p")
    store.append_message("p", "user", "foreign tail")
    ceiling = store.get_active_message_watermark("p")
    store.append_message("p", "assistant", "own flushed handoff")
    store.end_session("p", "ws_disconnect")
    assert store.try_acquire_compression_lock("p", "owner")
    store.publish_compression_child(parent_session_id="p", child_session_id="c", source="test",
        messages=[{"role": "assistant", "content": "own flushed handoff"}], compression_lock_holder="owner",
        watermark=mark, watermark_ceiling=ceiling)
    assert [row["content"] for row in store.get_messages("c")] == ["own flushed handoff", "foreign tail"]
    assert store.get_session("p")["end_reason"] == "compression"
