"""Durable transcript contracts shared by original SQLite and Core execution."""

import pytest


def test_full_message_payload_and_cache_sidecars(store):
    store.create_session("s", "cli")
    calls = [{"id": "call_1", "type": "function", "function": {"name": "read", "arguments": '{"p":"中"}'}}]
    row_id = store.append_message("s", "assistant", "正文\x00尾", tool_calls=calls,
        token_count=9, finish_reason="tool_calls", reasoning="推理\x00",
        reasoning_content="", reasoning_details=[{"text": "think"}],
        codex_reasoning_items=[{"type": "reasoning", "id": "r"}],
        codex_message_items=[{"type": "message"}], api_content="  API\x00\n",
        platform_message_id="remote", display_kind="answer", display_metadata={"tag": "值"}, message_uid="uid")
    row = store.get_messages("s")[0]
    assert row["id"] == row_id and row["content"] == "正文\x00尾"
    assert row["tool_calls"] == calls and row["token_count"] == 9
    assert row["message_uid"] == "uid" and row["api_content"] == "  API\x00\n"
    replay = store.get_messages_as_conversation("s")[0]
    assert replay["reasoning"] == "推理\x00" and replay["reasoning_content"] == ""
    assert replay["reasoning_details"] == [{"text": "think"}]
    assert replay["codex_reasoning_items"] == [{"type": "reasoning", "id": "r"}]
    assert replay["api_content"] == "  API\x00\n" and replay["message_id"] == "remote"
    assert store.get_session("s")["message_count"] == 1
    assert store.get_session("s")["tool_call_count"] == 1


def test_structured_content_literal_marker_and_blob(store):
    store.create_session("s", "cli")
    payloads = [[{"type": "text", "text": "多模态"}, {"type": "image_url", "image_url": {"url": "data:x"}}],
                {"text": "值"}, "\x00json:[1]", b"\x00\xffblob", None, 42]
    for payload in payloads:
        store.append_message("s", "user", payload)
    assert [row["content"] for row in store.get_messages("s")] == [*payloads[:-1], "42"]


def test_batch_order_identity_and_row_addressed_sidecar(store):
    store.create_session("s", "cli")
    batch = [{"role": "user", "content": "same", "timestamp": 100},
             {"role": "assistant", "content": "answer", "timestamp": 90},
             {"role": "user", "content": "same", "timestamp": 100}]
    assert store.append_messages_batch("s", batch) == 3
    assert len({msg["message_uid"] for msg in batch}) == 3
    ids = [row["id"] for row in store.get_messages("s")]
    assert ids == [msg["_row_id"] for msg in batch]
    assert store.set_message_api_content("s", ids[0], "same", "first\x00") == 1
    assert store.set_message_api_content("s", ids[-1], "wrong", "bad") == 0
    rows = store.get_messages("s")
    assert rows[0]["api_content"] == "first\x00" and rows[-1]["api_content"] is None
    assert [row["id"] for row in store.get_messages("s", latest=True, limit=2)] == ids[-2:]
    assert [row["id"] for row in store.get_messages("s", after_id=ids[0])] == ids[1:]
    with pytest.raises(ValueError):
        store.get_messages("s", after_id=ids[0], latest=True)


def test_tool_occurrence_identity_and_resume_model_boundary(store):
    store.create_session("s", "cli")
    calls = [{"id": "repeat", "type": "function", "function": {"name": "read", "arguments": "{}"}}]
    batch = [{"role": "session_meta", "content": "metadata"}, {"role": "user", "content": "ask"},
             {"role": "assistant", "content": None, "tool_calls": calls},
             {"role": "tool", "content": "result", "tool_call_id": "repeat", "tool_name": "read"},
             {"role": "assistant", "content": "done"}]
    assert store.append_messages_batch("s", batch) == 5
    model, display = store.get_resume_conversations("s")
    assert all(row["role"] != "session_meta" for row in model)
    assert any(row["role"] == "session_meta" for row in display)
    assistant, result = model[1:3]
    assert assistant["_tool_call_uids"]["repeat"] == result["_tool_call_uid"]
    assert store.get_active_message_watermark("s") == batch[-1]["_row_id"]
    assert store.get_active_message_ids("s") == [msg["_row_id"] for msg in batch]


def test_batch_failure_rolls_back_and_restores_physical_stamps(store):
    store.create_session("s", "cli")
    batch = [{"role": "user", "content": "new"}, {"role": "assistant", "content": "bad", "token_count": object()}]
    with pytest.raises(Exception):
        store.append_messages_batch("s", batch)
    assert store.message_count("s") == 0 and store.get_session("s")["message_count"] == 0
    assert all("_row_id" not in msg and "timestamp" not in msg for msg in batch)
    assert all(msg.get("message_uid") for msg in batch)


def test_preview_keeps_first_user_even_when_inactive(store):
    store.create_session("s", "cli")
    store.append_message("s", "user", "hidden scaffold", display_kind="hidden", timestamp=100)
    row = store.append_message("s", "user", "真实\n请求", timestamp=101)
    store.append_message("s", "user", "later", timestamp=102)
    store.deactivate_message("s", row)
    assert store.list_sessions_rich()[0]["preview"] == "真实 请求"


def test_compression_closed_parent_refuses_late_appends(store):
    from hermes_state_errors import CompressionSessionClosedError

    store.create_session("s", "cli")
    store.append_message("s", "user", "ask")
    store.end_session("s", "compression")
    with pytest.raises(CompressionSessionClosedError):
        store.append_messages_batch("s", [{"role": "assistant", "content": "late"}])
    assert store.message_count("s") == 1


def test_preview_projection_of_structured_and_nul_content(store):
    for session_id, content, expected in [("structured", [{"type": "text", "text": "part"}], ""),
                                          ("literal", "\x00json:[1]", ""), ("nul", "head\x00tail", "head")]:
        store.create_session(session_id, "cli")
        store.append_message(session_id, "user", content)
        rows = {row["id"]: row for row in store.list_sessions_rich()}
        assert rows[session_id]["preview"] == expected
