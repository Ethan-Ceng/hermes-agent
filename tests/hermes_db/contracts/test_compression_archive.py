"""Atomic compaction coverage, tail preservation and stale-held-row fencing."""

from copy import deepcopy

import pytest


def test_compaction_keeps_late_tail_uid_and_every_payload_column(store):
    store.create_session("s", "test", model_config={"keep": 1, "remove": True})
    store.append_message("s", "user", "before")
    mark = store.get_active_message_watermark("s")
    tail_id = store.append_message("s", "assistant", "late\x00reply", reasoning="reason\x00",
        reasoning_details=[{"type": "text", "text": "detail"}], api_content="wire\x00",
        tool_calls=[{"id": "call", "function": {"name": "x", "arguments": "{}"}}],
        platform_message_id="platform", display_metadata={"key": "value"}, timestamp=1234.5)
    original = next(row for row in store.get_messages("s") if row["id"] == tail_id)
    summary = [{"role": "user", "content": "summary", "_compressed_summary": True}]
    assert store.archive_and_compact("s", summary, watermark=mark,
        model_config_patch={"remove": None, "added": "yes"}) == 2
    live = store.get_messages("s")
    assert [row["content"] for row in live] == ["summary", "late\x00reply"]
    clone = live[-1]
    ignored = {"id", "display_order", "active", "compacted"}
    assert {key: value for key, value in clone.items() if key not in ignored} == {
        key: value for key, value in original.items() if key not in ignored}
    info = store.get_session("s")
    assert (info["message_count"], info["tool_call_count"]) == (2, 1)
    import json
    assert json.loads(info["model_config"]) == {"keep": 1, "added": "yes"}
    history = store.get_messages("s", include_inactive=True)
    assert next(row for row in history if row["id"] == tail_id)["compacted"] == 0
    assert next(row for row in history if row["content"] == "before")["compacted"] == 1


def test_named_coverage_preserves_unheld_gaps_below_watermark(store):
    store.create_session("s", "test")
    first = store.append_message("s", "user", "held one")
    gap = store.append_message("s", "assistant", "unseen gap")
    last = store.append_message("s", "user", "held last")
    mark = store.get_active_message_watermark("s")
    summary = [{"role": "user", "content": "summary"}]
    assert store.archive_and_compact("s", summary, watermark=mark, covered_ids=[first, last]) == 2
    assert [row["content"] for row in store.get_messages("s")] == ["summary", "unseen gap"]
    assert next(row for row in store.get_messages("s", include_inactive=True) if row["id"] == gap)["compacted"] == 0


def test_compaction_does_not_clone_an_already_carried_tail_occurrence(store):
    store.create_session("s", "test")
    store.append_message("s", "user", "old")
    mark = store.get_active_message_watermark("s")
    carried = [{"role": "user", "content": "carried once"}]
    store.append_messages_batch("s", carried)
    summary = [{"role": "assistant", "content": "summary"}, deepcopy(carried[0])]
    assert store.archive_and_compact("s", summary, watermark=mark, tail_count=1) == 2
    assert [row["content"] for row in store.get_messages("s")] == ["summary", "carried once"]


def test_compaction_refuses_lost_holder_and_rewritten_held_rows(store):
    from hermes_state_errors import HeldRowRewrittenError, SessionCompressionInProgressError

    store.create_session("s", "test")
    held = [{"role": "user", "content": "old"}]
    store.append_messages_batch("s", held)
    held[0]["_db_persisted"] = True
    store.set_user_message_content("s", held[0]["_row_id"], "current")
    summary = [{"role": "user", "content": "stale summary"}]
    before = deepcopy(summary)
    with pytest.raises(HeldRowRewrittenError):
        store.archive_and_compact("s", summary, held_for_cas=held, model_config_patch={"no": "write"})
    assert "_row_id" not in summary[0] and summary[0]["content"] == before[0]["content"]
    assert store.try_acquire_compression_lock("s", "current")
    with pytest.raises(SessionCompressionInProgressError):
        store.archive_and_compact("s", summary, lock_holder="displaced")
    assert [row["content"] for row in store.get_messages("s")] == ["current"]
    assert store.get_session("s")["model_config"] is None
