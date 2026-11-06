"""A proactive prune preserves ids, archived bodies and stale-writer exclusion."""

from copy import deepcopy

import pytest

from agent.message_metadata import DB_ROW_SNAPSHOT
from hermes_state_errors import PruneRowStaleError


def test_prune_keeps_row_slot_and_archives_only_changed_body(store):
    store.create_session("s", "cli")
    held = [{"role": "user", "content": "ask", "_db_persisted": True},
            {"role": "assistant", "content": "long\x00body", "reasoning": "held reasoning", "_db_persisted": True},
            {"role": "user", "content": "tail", "_db_persisted": True}]
    store.append_messages_batch("s", held)
    original = held[1]
    replacement = {**original, "content": "stub\x00"}
    old_snapshot = original[DB_ROW_SNAPSHOT]
    assert store.rewrite_pruned_rows("s", [(original, replacement)], model_config_patch={"pruned": True}) == 1
    live = store.get_messages_as_conversation("s", include_row_ids=True)
    assert [m["_row_id"] for m in live] == [m["_row_id"] for m in held]
    assert live[1]["content"] == "stub\x00" and replacement[DB_ROW_SNAPSHOT] != old_snapshot
    archived = store.get_messages("s", include_inactive=True)
    assert len(archived) == 4 and sum(m["content"] == "long\x00body" for m in archived) == 1
    display = store.get_messages("s", include_compacted=True)
    assert [m["content"] for m in display] == ["ask", "stub\x00", "tail"]
    store.append_message("s", "assistant", "new tail")
    assert [m["content"] for m in store.get_messages("s", include_compacted=True)] == ["ask", "stub\x00", "tail", "new tail"]
    assert store.rewritten_held_row_ids("s", held) == [original["_row_id"]]
    with pytest.raises(PruneRowStaleError):
        store.rewrite_pruned_rows("s", [(original, {**original, "content": "stale overwrite"})])
    assert store.get_session("s")["message_count"] == 4


def test_prune_prevalidates_every_row_before_writing_or_stamping(store):
    store.create_session("s", "cli")
    store.append_message("s", "assistant", "one")
    store.append_message("s", "assistant", "two")
    held = store.get_messages_as_conversation("s", include_row_ids=True)
    first = {**held[0], "content": "stub"}
    stale = {**held[1], DB_ROW_SNAPSHOT: "stale"}
    before = deepcopy(first)
    with pytest.raises(PruneRowStaleError):
        store.rewrite_pruned_rows("s", [(held[0], first), (stale, {**stale, "content": "bad"})], model_config_patch={"must_not_commit": True})
    assert first == before
    assert [m["content"] for m in store.get_messages("s", include_inactive=True)] == ["one", "two"]
    assert "must_not_commit" not in (store.get_session("s")["model_config"] or "")


def test_rewind_user_turn_uses_public_projection_and_rejects_changed_warm_history(store):
    store.create_session("s", "cli")
    for role, text in [("user", "one"), ("assistant", "answer"), ("user", "retry\x00"), ("assistant", "last")]:
        store.append_message("s", role, text)
    warm = store.get_messages_as_conversation("s", include_row_ids=True)
    with pytest.raises(RuntimeError, match="history changed"):
        store.rewind_user_turn("s", -1, warm_history=[*warm[:2], {**warm[2], "content": "moved"}])
    result = store.rewind_user_turn("s", -1, warm_history=warm, require_retryable=True, adopt_row_ids=True)
    assert result.live_text == "retry\x00" and result.rewound_count == 2
    assert [m["content"] for m in result.prefix] == ["one", "answer"]
