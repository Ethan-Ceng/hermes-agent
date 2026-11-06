"""Same message/session metadata in one schema never crosses store boundaries."""


def test_message_queries_mutations_and_results_are_scoped(core_pair):
    one, two = core_pair
    for store in core_pair:
        store.create_session("s", "api")
    row_one = one.append_message("s", "user", "same", platform_message_id="remote", display_metadata={"gateway_input_owner": "owner"})
    row_two = two.append_message("s", "user", "same", platform_message_id="remote", display_metadata={"gateway_input_owner": "owner"})
    assert one.set_message_api_content("s", row_two, "same", "foreign") == 0
    assert one.set_message_reaction("s", row_two, "👍") is None
    assert one.get_messages_around("s", row_two)["window"] == []
    assert one.get_message_role("s", row_two) is None
    assert one.deactivate_message("s", row_two) == 0
    assert one.has_gateway_input_owner("s", "owner") and two.has_platform_message_id("s", "remote")
    note_one = one.append_completion_note("s", "a", "first", "notice", {})
    note_two = two.append_completion_note("s", "a", "second", "notice", {})
    assert note_one != note_two and row_one != row_two
    one.clear_messages("s")
    assert one.message_count() == 0 and two.message_count() == 2
    assert two.get_messages("s")[0]["content"] == "same"


def test_lost_commit_confirmation_retains_identity_without_replaying(core_pair, monkeypatch):
    from contextlib import contextmanager
    import pytest
    from hermes_db.errors import UnknownCommitError

    store = core_pair[0]
    store.create_session("s", "cli")
    original_write = store._transactions.write

    @contextmanager
    def lose_confirmation():
        with original_write() as conn:
            yield conn
        raise UnknownCommitError("Lost commit confirmation")

    monkeypatch.setattr(store._transactions, "write", lose_confirmation)
    batch = [{"role": "user", "content": "one"}]
    with pytest.raises(UnknownCommitError):
        store.append_messages_batch("s", batch)
    assert batch[0]["message_uid"] and "_row_id" not in batch[0] and "timestamp" not in batch[0]
    rows = store.get_messages("s")
    assert len(rows) == 1 and rows[0]["message_uid"] == batch[0]["message_uid"]
