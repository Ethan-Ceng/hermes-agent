"""Peer identity, recovery boundaries and orphan repair contracts."""

import time


def test_peer_record_self_heals_and_repoints_compression_ancestors(store):
    peer = dict(source="telegram", user_id="u", session_key="agent:main:chat", chat_id="chat", chat_type="dm")
    store.record_gateway_session_peer("p", **peer, display_name="Name\x00", origin_json='{"owner":"u"}')
    assert store.get_session("p")["source"] == "telegram"
    store.end_session("p", "compression")
    store.create_session("c", "telegram", parent_session_id="p")
    store.record_gateway_session_peer("c", **(peer | {"session_key": "agent:main:new"}), include_compression_ancestors=True)
    for sid in ("p", "c"):
        row = store.get_session(sid)
        assert row["session_key"] == "agent:main:new" and row["display_name"] == "Name\x00"
    assert store.find_latest_gateway_session_for_peer(**(peer | {"session_key": "agent:main:new"}))["id"] == "c"
    assert [row["id"] for row in store.list_gateway_sessions(platform="TELEGRAM")] == ["c"]


def test_peer_recovery_does_not_reach_behind_reset_boundary(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    peer = dict(source="telegram", user_id="u", session_key="key", chat_id="chat", chat_type="dm", thread_id="thread")
    store.create_session("old", "telegram", **{key: value for key, value in peer.items() if key != "source"})
    store.append_message("old", "user", "old turn")
    store.end_session("old", "agent_close")
    recovered = store.find_latest_gateway_session_for_peer(**peer)
    assert recovered["id"] == "old" and recovered["_has_messages"]
    clock[0] += 10
    store.create_session("boundary", "telegram", **{key: value for key, value in peer.items() if key != "source"})
    store.end_session("boundary", "session_reset")
    assert store.find_latest_gateway_session_for_peer(**peer) is None
    assert store.find_latest_gateway_session_for_peer(**(peer | {"session_key": "missing"})) is None


def test_orphan_lineage_adoption_keeps_non_null_peer_fields_and_closes_donor(store):
    store.create_session("donor", "telegram", session_key="key", user_id="user", chat_id="chat", chat_type="dm")
    store.create_session("orphan", "telegram", parent_session_id="donor", display_name="Own name")
    store.append_message("orphan", "user", "durable")
    records = store.find_orphaned_gateway_sessions()
    assert len(records) == 1 and records[0]["donor_id"] == "donor" and records[0]["evidence"] == "lineage"
    assert store.adopt_orphaned_gateway_session("orphan", "donor")
    assert not store.adopt_orphaned_gateway_session("orphan", "donor")
    row = store.get_session("orphan")
    assert row["session_key"] == "key" and row["chat_id"] == "chat" and row["display_name"] == "Own name"
    assert store.get_session("donor")["end_reason"] == "superseded_by_repair"


def test_never_active_selector_protects_user_keep_intent_and_any_history(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for sid in ("unused", "pinned", "history", "used"):
        store.create_session(sid, "telegram", session_key=sid)
    store.set_session_pinned("pinned", True)
    store.append_message("history", "user", "present")
    store.update_token_counts("used", api_call_count=1)
    clock[0] += 3 * 86400
    assert [row["id"] for row in store.list_never_active_keyed_sessions(older_than_days=2)] == ["unused"]


def test_orphan_time_window_ambiguity_never_guesses_a_peer(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for sid in ("one", "two"):
        store.create_session(sid, "telegram", user_id="user", session_key=sid)
        store.append_message(sid, "user", "prior")
    clock[0] += 10
    store.create_session("orphan", "telegram", user_id="user")
    store.append_message("orphan", "user", "new")
    row = store.find_orphaned_gateway_sessions()[0]
    assert not row["adoptable"] and row["reason"].startswith("ambiguous:")


def test_core_messaging_takeover_settles_local_receipt_history_and_title(core_pair):
    import json
    from hermes_db.domains.runtime.postgres.queries import runtime
    from hermes_state_keys import local_identity
    from hermes_db.domains.runtime.receipts import POLICY_PREFIX

    store, _ = core_pair
    root = local_identity("profile", "human", "request")
    old_route = "local-route"
    identity = dict(chat_id=root, user_id="human", session_key=old_route)
    store.create_session(root, "local", **identity)
    store.set_session_title(root, "Personal title")
    store.end_session(root, "session_reset")
    store.create_session("tip", "local", parent_session_id=root, model_config={"_reset_from": root}, **identity)
    store.set_auto_title("tip", "Generated", source="derived")
    receipt = dict(session_id=root, profile_id="profile", principal_id="human", request_id="request",
        route=old_route, entry={"session_id": "tip"}, lineage=[root, "tip"])
    with store._write() as conn:
        runtime.set_meta(conn, store.scope, POLICY_PREFIX + root, json.dumps(receipt))
    store.record_gateway_session_peer("tip", source="telegram", user_id="telegram-user", chat_id="telegram-chat",
        chat_type="dm", session_key="telegram-route", include_compression_ancestors=True)
    with store._read() as conn:
        assert runtime.meta(conn, store.scope, POLICY_PREFIX + root) is None
    for sid in (root, "tip"):
        row = store.get_session(sid)
        assert row["source"] == "telegram" and row["session_key"] == "telegram-route"
    assert store.get_session_title(root) is None and store.get_session_title("tip") == "Personal title"
