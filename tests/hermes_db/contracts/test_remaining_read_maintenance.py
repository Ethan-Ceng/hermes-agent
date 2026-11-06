"""Late capability audit covers current reads and maintenance, without SQLite fixups."""

import time


def test_literal_metadata_and_rich_session_reads(store):
    store.set_meta("user:%_", "literal")
    store.set_meta("user:XX", "other")
    assert store.get_meta("user:%_") == "literal"
    assert store.list_meta_prefix("user:%_") == [("user:%_", "literal")]
    store.create_session("s", "cli")
    store.append_message("s", "user", "question")
    assert store.get_session_rich_row("s")["preview"] == "question"
    assert store.get_session_rich_row("absent") is None


def test_anchored_bookends_and_recent_user_turns_keep_the_public_shape(store):
    store.create_session("s", "cli")
    ids = [store.append_message("s", "user" if index % 2 == 0 else "assistant", f"turn {index}") for index in range(12)]
    anchor = ids[5]
    view = store.get_anchored_view("s", anchor, window=1, bookend=2)
    assert [row["id"] for row in view["window"]] == ids[4:7]
    assert [row["id"] for row in view["bookend_start"]] == ids[:2]
    assert [row["id"] for row in view["bookend_end"]] == ids[-2:]
    assert [row["preview"] for row in store.list_recent_user_messages("s", limit=2)] == ["turn 10", "turn 8"]
    assert store.get_anchored_view("absent", anchor)["window"] == []


def test_kanban_provenance_follows_only_the_verified_compression_chain(store):
    store.create_session("worker", "kanban")
    store.end_session("worker", "compression")
    store.create_session("tip", "cli", parent_session_id="worker")
    assert store.is_kanban_owned_session("tip")
    store.create_session("branch", "cli", parent_session_id="worker", model_config={"_branched_from": "worker"})
    assert not store.is_kanban_owned_session("branch")


def test_empty_tui_ghost_pruning_keeps_real_history_and_fresh_rows(store, monkeypatch):
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now - 90000)
    for sid in ("old", "history"):
        store.create_session(sid, "tui")
        store.end_session(sid, "done")
    store.append_message("history", "user", "keep")
    monkeypatch.setattr(time, "time", lambda: now)
    store.create_session("fresh", "tui")
    store.end_session("fresh", "done")
    assert store.prune_empty_ghost_sessions() == 1
    assert store.get_session("old") is None and store.get_session("fresh") and store.get_session("history")


def test_profile_identity_purge_leaves_session_history_and_other_names(store):
    import json
    for profile in ("gone", "gone-more"):
        key = f"agent:{profile}:telegram:dm:chat"
        store.create_session(profile, "telegram", session_key=key, profile_name=profile)
        store.save_gateway_routing_entry(key, json.dumps({"session_id": profile}))
        store.register_backend_heartbeat(backend_id=profile, pid=1, started_at=0, profile=profile)
    counts = store.purge_profile_state("gone")
    assert counts["gateway_routing"] == 1 and counts["gateway_heartbeats"] == 1
    assert list(store.load_gateway_routing_entries()) == ["agent:gone-more:telegram:dm:chat"]
    assert store.get_session("gone") is not None
    assert store.purge_profile_state("gone")["gateway_routing"] == 0


def test_core_metadata_and_profile_purge_are_scoped_and_terminal_delivery_is_preserved(core_pair):
    from sqlalchemy import select
    from hermes_db.tables.gateway import delivery_obligations
    first, other = core_pair
    for store in core_pair:
        store.set_meta("same:key", store.scope.store_id)
        for sid in ("pending", "delivered"):
            with store._write() as conn:
                conn.execute(delivery_obligations.insert().values(store_id=store.scope.store_id, obligation_id=sid,
                    session_key="agent:gone:telegram:dm:chat", adapter_profile="gone", platform="telegram",
                    chat_id="chat", content=b"body", state=sid, created_at=0, updated_at=0))
    assert first.get_meta("same:key") == first.scope.store_id
    assert other.list_meta_prefix("same:") == [("same:key", other.scope.store_id)]
    assert first.purge_profile_state("gone")["delivery_obligations"] == 1
    for store in core_pair:
        with store._read() as conn:
            rows = dict(conn.execute(select(delivery_obligations.c.obligation_id, delivery_obligations.c.state).where(
                delivery_obligations.c.store_id == store.scope.store_id)).all())
        assert rows == {"pending": "abandoned" if store is first else "pending", "delivered": "delivered"}
