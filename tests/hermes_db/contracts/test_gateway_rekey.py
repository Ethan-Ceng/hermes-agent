"""Exact profile identity settlement is atomic and keeps stable store ownership."""

import json

import pytest


def test_profile_rekey_changes_exact_identity_and_literal_namespace(store):
    old, new = "old_%", "renamed"
    old_key = f"agent:{old}:chat"
    new_key = f"agent:{new}:chat"
    store.create_session("s", "telegram", profile_name=old, session_key=old_key, origin_json=json.dumps({"profile": old}))
    store.create_session("other", "telegram", profile_name="oldX", session_key="agent:oldX:chat")
    entry = {"session_id": "s", "session_key": old_key, "origin": {"profile": old}, "text": old}
    store.save_gateway_routing_entry(old_key, json.dumps(entry), scope="scope")
    store.register_backend_heartbeat(backend_id="backend", pid=1, started_at=1, profile=old)
    counts = store.rekey_profile_state(old, new)
    assert {key: counts[key] for key in ("sessions_profile_name", "sessions_session_key", "sessions_origin_json",
        "gateway_routing", "gateway_heartbeats_profile")} == dict(sessions_profile_name=1, sessions_session_key=1,
        sessions_origin_json=1, gateway_routing=1, gateway_heartbeats_profile=1)
    row = store.get_session("s")
    assert row["profile_name"] == new and row["session_key"] == new_key
    assert json.loads(row["origin_json"])["profile"] == new
    routed = json.loads(store.load_gateway_routing_entries(scope="scope")[new_key])
    assert routed["origin"]["profile"] == new and routed["session_key"] == new_key and routed["text"] == old
    assert store.get_session("other")["profile_name"] == "oldX"
    assert store.list_backend_heartbeats()[0]["profile"] == new
    assert store.rekey_profile_state(new, new) == {}


def test_profile_rekey_collision_rolls_back_all_identity_changes(store):
    store.create_session("s", "telegram", profile_name="old", session_key="agent:old:chat")
    store.save_gateway_routing_entry("agent:old:chat", '{"session_id":"s"}')
    store.save_gateway_routing_entry("agent:new:chat", '{"session_id":"other"}')
    before = store.load_gateway_routing_entries()
    with pytest.raises(ValueError, match="profile routing collision"):
        store.rekey_profile_state("old", "new")
    assert store.load_gateway_routing_entries() == before
    assert store.get_session("s")["profile_name"] == "old"


def test_core_profile_rekey_never_treats_another_store_as_collision(core_pair):
    first, second = core_pair
    first.create_session("same", "telegram", profile_name="old", session_key="agent:old:chat")
    first.save_gateway_routing_entry("agent:old:chat", '{"session_id":"same"}')
    second.create_session("same", "telegram", profile_name="old", session_key="agent:new:chat")
    second.save_gateway_routing_entry("agent:new:chat", '{"session_id":"same"}')
    owner = first.scope.store_id
    first.rekey_profile_state("old", "new")
    assert first.scope.store_id == owner
    assert first.get_session("same")["profile_name"] == "new"
    assert second.get_session("same")["profile_name"] == "old"


def test_core_profile_rekey_retains_permanent_namespace_retirement_fences(core_pair, monkeypatch):
    import time
    first, second = core_pair
    for store in core_pair:
        store.retire_gateway_routes(["retired"], namespace="old_%")
        store.retire_gateway_routes(["retired"], namespace="new", expiring=["retired"])
    first.rekey_profile_state("old_%", "new")
    later = time.time() + 8 * 86400
    monkeypatch.setattr(time, "time", lambda: later)
    routes = {"agent:new:chat": '{"session_id":"retired"}', "agent:old_%:chat": '{"session_id":"retired"}'}
    assert first.replace_gateway_routing_entries(routes) == set(routes)
    assert second.replace_gateway_routing_entries({"agent:new:other": '{"session_id":"retired"}'}) == set()


def test_profile_rekey_moves_current_topic_identity_and_binding_namespace(store):
    store.apply_telegram_topic_migration()
    store.create_session("s", "telegram", profile_name="old", session_key="agent:old:chat")
    store.enable_telegram_topic_mode(chat_id="chat", user_id="u", profile_name="old")
    store.bind_telegram_topic(chat_id="chat", thread_id="thread", user_id="u", profile_name="old",
        session_key="agent:old:chat", session_id="s")
    counts = store.rekey_profile_state("old", "new")
    assert counts["telegram_dm_topic_mode_profile_name"] == 1
    assert counts["telegram_dm_topic_bindings_profile_name"] == 1
    assert store.is_telegram_topic_mode_enabled(chat_id="chat", user_id="u", profile_name="new")
    binding = store.get_telegram_topic_binding(chat_id="chat", thread_id="thread", profile_name="new")
    assert binding["session_key"] == "agent:new:chat" and binding["session_id"] == "s"
    assert store.get_telegram_topic_binding(chat_id="chat", thread_id="thread", profile_name="old") is None


def test_profile_rekey_topic_collision_preserves_session_owner(store):
    store.apply_telegram_topic_migration()
    store.create_session("s", "telegram", profile_name="old")
    for profile in ("old", "new"):
        store.enable_telegram_topic_mode(chat_id="same-chat", user_id="u", profile_name=profile)
    with pytest.raises(ValueError, match="profile identity collision"):
        store.rekey_profile_state("old", "new")
    assert store.get_session("s")["profile_name"] == "old"


def test_core_profile_rekey_delivery_rows_stay_in_own_store(core_pair):
    from sqlalchemy import select
    from hermes_db.tables.gateway import delivery_obligations as deliveries

    for store in core_pair:
        with store._write() as conn:
            conn.execute(deliveries.insert().values(store_id=store.scope.require_store_id(), obligation_id="same",
                session_key="agent:old:chat", adapter_profile="old", platform="telegram", chat_id="chat", state="pending",
                content=b"outbox\x00", created_at=1, updated_at=1))
    core_pair[0].rekey_profile_state("old", "new")
    for index, store in enumerate(core_pair):
        expected = "new" if index == 0 else "old"
        with store._read() as conn:
            row = conn.execute(select(deliveries).where(deliveries.c.store_id == store.scope.require_store_id())).mappings().one()
            assert row["adapter_profile"] == expected and row["session_key"] == f"agent:{expected}:chat"
            assert row["content"] == b"outbox\x00" and row["state"] == "pending"
