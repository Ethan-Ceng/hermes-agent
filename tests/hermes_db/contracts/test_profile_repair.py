"""Identity repair is scoped and rechecks the current evidence before writing."""

import json


def test_profile_repair_relabels_keys_severs_crossed_parents_and_rekeys_main(store):
    store.create_session("parent", "telegram", session_key="agent:alpha:telegram:dm:chat", profile_name="alpha", chat_id="chat")
    store.create_session("child", "telegram", session_key="agent:beta:telegram:dm:chat", profile_name="wrong",
        parent_session_id="parent", chat_id="chat")
    found = store.find_crossed_profile_sessions("default")
    assert {row["id"] for row in found["foreign"]} == {"parent", "child"}
    assert found["crossed_parents"][0]["id"] == "child"
    assert store.relabel_sessions_to_key_profile(["child"]) == 1
    assert store.get_session("child")["profile_name"] == "beta"
    assert store.sever_crossed_parents(["child"]) == 1
    assert store.get_session("child")["parent_session_id"] is None
    assert store.key_profiles_for_chat("telegram", "chat") == {"alpha", "beta"}
    store.create_session("main", "cli", session_key="agent:main:cli:chat")
    assert store.rekey_legacy_main_sessions(["main"], "alpha") == 1
    assert store.get_session("main")["session_key"] == "agent:alpha:cli:chat"


def test_routing_repair_is_idempotent_and_preserves_resident_entry(store):
    key = "agent:alpha:telegram:dm:chat"
    old, newer = json.dumps({"session_id": "s"}), json.dumps({"session_id": "new"})
    assert store.insert_gateway_routing_rows_if_absent([("index", key, old, 1)]) == 1
    assert store.insert_gateway_routing_rows_if_absent([("index", key, newer, 2)]) == 0
    assert store.list_gateway_routing_rows() == [dict(scope="index", session_key=key, entry_json=old, updated_at=1)]
    assert store.delete_gateway_routing_rows([("other", key)]) == 0
    assert store.delete_gateway_routing_rows([("index", key)]) == 1


def test_core_repair_rechecks_topic_key_and_never_changes_another_store(core_pair):
    store, other = core_pair
    for db in core_pair:
        db.create_session("s", "telegram", session_key="agent:alpha:telegram:dm:chat")
        db.enable_telegram_topic_mode(chat_id="chat", user_id="user")
        db.bind_telegram_topic(chat_id="chat", thread_id="thread", user_id="user",
            session_key="agent:alpha:telegram:dm:chat", session_id="s")
    evidence = store.find_profile_less_telegram_topic_rows()
    assert evidence[0]["key_profile"] == "alpha"
    assert store.relabel_telegram_topic_rows(evidence) == {
        "bindings_relabelled": 1, "bindings_duplicates_removed": 0, "mode_rows_relabelled": 1}
    assert store.get_telegram_topic_binding(chat_id="chat", thread_id="thread", profile_name="alpha")
    assert other.get_telegram_topic_binding(chat_id="chat", thread_id="thread")
    assert store.relabel_telegram_topic_rows(evidence)["bindings_relabelled"] == 0
