"""Row ownership, display and between-turn result contracts."""

from copy import deepcopy
import json

import pytest


def test_rewrite_snapshot_preserves_metadata_and_adopts_concurrent_winner(store):
    from agent.message_metadata import CANONICAL_ROW

    store.create_session("s", "cli")
    batch = [{"role": "user", "content": "ask"}, {"role": "assistant", "content": "first", "token_count": 7}]
    store.append_messages_batch("s", batch)
    winner, loser = deepcopy(batch[1]), deepcopy(batch[1])
    assert store.set_latest_matching_message_display_kind("s", role="assistant", content="first", display_kind="answer")
    winner["content"] = "winner"
    assert store.append_messages_batch("s", [winner]) == 0
    loser["content"] = "loser"
    assert store.append_messages_batch("s", [loser]) == 0
    assert loser[CANONICAL_ROW]["content"] == "winner"
    rows = store.get_messages("s")
    assert len(rows) == 2 and rows[1]["content"] == "winner"
    assert rows[1]["token_count"] == 7 and rows[1]["display_kind"] == "answer"


def test_replace_keeps_prefix_and_rewind_never_displays_removed_tail(store):
    store.create_session("s", "cli")
    batch = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "answer"},
             {"role": "user", "content": "two"}, {"role": "assistant", "content": "last"}]
    store.append_messages_batch("s", batch)
    store.replace_messages("s", [deepcopy(msg) for msg in batch[:2]], archive_dropped=True)
    assert store.get_active_message_ids("s") == [msg["_row_id"] for msg in batch[:2]]
    assert store.message_count("s") == 4
    assert [row["content"] for row in store.get_messages("s", include_compacted=True)] == ["one", "answer"]
    current = store.conversation_revision("s")
    store.set_user_message_content("s", batch[0]["_row_id"], "edited", {"x": 1})
    assert store.conversation_revision("s") != current
    result = store.rewind_to_message("s", batch[0]["_row_id"], expected_active_ids=store.get_active_message_ids("s"),
                                    expected_target_content="edited")
    assert result["rewound_count"] == 2 and result["new_head_id"] is None
    assert store.get_session("s")["message_count"] == 0 and store.get_session("s")["rewind_count"] == 1
    assert store.display_message_count("s") == 0


def test_rewrite_cas_failure_changes_nothing(store):
    store.create_session("s", "cli")
    row_id = store.append_message("s", "user", "ask")
    store.append_message("s", "assistant", "answer")
    before = store.conversation_revision("s")
    with pytest.raises(RuntimeError):
        store.rewind_to_message("s", row_id, expected_active_ids=[row_id])
    assert store.conversation_revision("s") == before and store.message_count("s") == 2


def test_reaction_toggle_and_seen_do_not_change_api_prefix(store):
    store.create_session("s", "cli")
    row_id = store.append_message("s", "user", "ask", api_content="exact\n")
    assert store.set_message_reaction("s", row_id, "👍")[0]["emoji"] == "👍"
    assert store.get_message_reactions("s", row_id)[0]["author"] == "user"
    pending = store.take_unseen_reactions("s")
    assert pending == [{"row_id": row_id, "role": "user", "emoji": "👍", "text": "ask"}]
    assert store.take_unseen_reactions("s") == []
    assert store.set_message_reaction("s", row_id, "👍") == []
    assert store.get_messages_as_conversation("s")[0]["api_content"] == "exact\n"


def test_result_delivery_and_completion_notes_are_durable_once(store):
    store.create_session("s", "api")
    delivery = store.append_delegation_delivery("s", "result", {"delegation_id": "d"})
    assert store.append_delegation_delivery("s", "changed", {"delegation_id": "d"}) == delivery
    note = store.append_completion_note("s", "a", "finished", "notice", {"task_count": 1})
    assert store.append_completion_note("s", "a", "changed", "notice", {}) == note
    store.deactivate_message("s", delivery)
    assert store.append_delegation_delivery("s", "changed", {"delegation_id": "d"}) == delivery
    assert store.message_count("s") == 2


def test_navigation_and_resume_guard(store):
    from hermes_state import SessionResumeTooLargeError

    store.create_session("s", "cli")
    ids = [store.append_message("s", role, content, platform_message_id=str(i))
           for i, (role, content) in enumerate([("user", "one"), ("assistant", "answer"), ("user", "two")])]
    assert store.latest_message_row_id("s") == ids[-1] and store.latest_message_row_id("s", offset=1) == ids[0]
    assert store.latest_conversation_role("s") == "user"
    assert store.get_message_role("s", ids[1]) == "assistant"
    assert store.has_platform_message_id("s", "1")
    around = store.get_messages_around("s", ids[1], window=1)
    assert [row["id"] for row in around["window"]] == ids
    assert around["messages_before"] == around["messages_after"] == 1
    assert store.get_resume_message_count("s") == 3 and store.assert_resume_safe("s", 3) == 3
    with pytest.raises(SessionResumeTooLargeError):
        store.assert_resume_safe("s", 2)


def test_todo_restores_only_latest_paired_valid_result(store):
    store.create_session("s", "cli")
    payload = json.dumps({"todos": [], "revision": 1})
    calls = [{"id": "todo1", "type": "function", "function": {"name": "todo_list", "arguments": "{}"}}]
    store.append_messages_batch("s", [{"role": "user", "content": "plan"},
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "content": payload, "tool_name": "todo_list", "tool_call_id": "todo1"}])
    store.append_message("s", "tool", "bad", tool_name="todo_list", tool_call_id="foreign")
    assert store.get_latest_todo_result("s") == payload
    assert store.get_latest_todo_result("s", max_chars=1) is None


def test_display_hides_model_only_and_paging_matches_count(store):
    from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY

    store.create_session("s", "cli")
    store.append_message("s", "user", "ask")
    store.append_message("s", "user", "scaffold", display_metadata={MODEL_ONLY_DISPLAY_METADATA_KEY: True})
    store.append_message("s", "assistant", "answer")
    rows = store.get_messages("s", include_compacted=True)
    assert [row["content"] for row in rows] == ["ask", "answer"]
    assert store.display_message_count("s") == 2
    assert store.get_messages("s", include_compacted=True, limit=1, latest=True) == rows[-1:]
