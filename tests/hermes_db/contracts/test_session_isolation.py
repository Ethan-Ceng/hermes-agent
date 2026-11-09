"""Offline Core isolation and rollback contracts, without claiming PG evidence."""

import pytest


def test_same_ids_titles_prompt_hashes_and_topic_ids_are_store_scoped(core_pair):
    one, two = core_pair
    for index, store in enumerate(core_pair):
        store.create_session("same", source="telegram", system_prompt="shared bytes")
        store.set_session_title("same", "same title")
        store.update_token_counts("same", input_tokens=index + 1, api_call_count=1)
        store.enable_telegram_topic_mode(chat_id="chat", user_id="u")
        store.bind_telegram_topic(chat_id="chat", thread_id="thread", user_id="u", session_key="key", session_id="same")
    one.set_session_hidden("same", True)
    one.update_system_prompt("same", "one only")
    assert two.get_session("same")["hidden"] == 0
    assert two.get_session("same")["system_prompt"] == "shared bytes"
    assert one.get_session("same")["input_tokens"] == 1
    assert two.get_session("same")["input_tokens"] == 2
    one.delete_telegram_topic_binding(chat_id="chat", thread_id="thread")
    assert two.get_telegram_topic_binding(chat_id="chat", thread_id="thread")["session_id"] == "same"
    assert one.session_count() == two.session_count() == 1


def test_constructor_failure_rolls_back_prompt_and_control_rows(core_pair, monkeypatch):
    from sqlalchemy import func, select
    from hermes_db.domains.sessions.postgres.queries import prompts
    from hermes_db.tables.conversations import sessions, system_prompts, transcript_roots

    store = core_pair[0]
    original = prompts.store_prompt

    def fail_after_prompt(conn, scope, value):
        original(conn, scope, value)
        raise ValueError("injected after prompt insert")

    monkeypatch.setattr(prompts, "store_prompt", fail_after_prompt)
    with pytest.raises(ValueError, match="injected"):
        store.create_session("s", source="cli", system_prompt="not committed")
    with store._transactions.read() as conn:
        for table in (sessions, system_prompts, transcript_roots):
            assert conn.scalar(select(func.count()).select_from(table)) == 0
