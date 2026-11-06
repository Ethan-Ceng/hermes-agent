"""Existing lifecycle and metadata behavior, without old-format migration."""

import json

import pytest


def test_creation_is_keep_existing_and_placeholder_source_is_replaced(store):
    store.ensure_session("s")
    store.create_session("s", source="cli", model="first", model_config={"a": 1}, cwd="/one")
    store.create_session("s", source="other", model="later", model_config={"a": 2}, cwd="/two")
    row = store.get_session("s")
    assert row["source"] == row["created_source"] == "cli"
    assert row["model"] == "first"
    assert json.loads(row["model_config"]) == {"a": 1}
    assert row["cwd"] == "/one"
    assert store.get_session("absent") is None


def test_end_is_first_writer_wins_and_reopen_allows_a_new_end(store):
    store.create_session("s", source="cli")
    store.end_session("s", "compression")
    store.end_session("s", "agent_close")
    assert store.get_session("s")["end_reason"] == "compression"
    store.reopen_session("s")
    assert store.get_session("s")["ended_at"] is None
    store.end_session("s", "agent_close")
    assert store.get_session("s")["end_reason"] == "agent_close"


def test_compression_child_inherits_metadata_but_branch_does_not_inherit_routing(store):
    store.create_session("parent", source="telegram", cwd="/work", git_repo_root="/repo",
                         user_id="u", session_key="route", chat_id="chat", thread_id="thread")
    store.end_session("parent", "compression")
    store.create_session("tip", source="telegram", parent_session_id="parent")
    store.create_session("branch", source="telegram", parent_session_id="parent",
                         model_config={"_branched_from": "parent"})
    assert store.get_session("tip")["session_key"] == "route"
    assert store.get_session("tip")["cwd"] == "/work"
    assert store.get_session("branch")["session_key"] is None
    assert store.get_session("branch")["cwd"] == "/work"


def test_lineage_visibility_flags_do_not_cross_explicit_branches(store):
    store.create_session("parent", source="cli")
    store.end_session("parent", "compression")
    store.create_session("tip", source="cli", parent_session_id="parent")
    store.create_session("branch", source="cli", parent_session_id="parent", model_config={"_branched_from": "parent"})
    assert store.set_session_hidden("tip", True)
    assert store.get_session("parent")["hidden"] == 1
    assert store.get_session("branch")["hidden"] == 0
    assert store.set_session_pinned("tip", True)
    assert store.get_session("parent")["hidden"] == 0
    assert store.set_session_archived("tip", True, notify=False)
    assert store.get_session("parent")["archived"] == 1
    assert store.get_session("branch")["archived"] == 0


def test_title_provenance_uniqueness_and_canonical_identity(store):
    store.create_session("s", source="cli")
    assert store.set_auto_title("s", "derived", source="derived")
    assert store.set_auto_title("s", "model title", source="llm")
    assert not store.set_auto_title("s", "second", source="llm")
    assert store.set_session_title("s", "manual")
    assert not store.set_auto_title("s", "later", source="llm")
    store.create_session("bot", source="cli")
    store.set_session_title("bot", "Bot Chat")
    store.set_session_hidden("bot", True)
    with pytest.raises(ValueError):
        store.set_session_title("bot", "renamed")
    store.create_session("other", source="cli")
    with pytest.raises(ValueError):
        store.set_session_title("other", "manual")


def test_cwd_generation_refuses_stale_background_enrichment(store):
    store.create_session("s", source="cli", cwd="/a")
    first = store.update_session_cwd("s", "/b")
    latest = store.update_session_cwd("s", "/a")
    assert latest > first
    assert not store.publish_session_git_metadata("s", "/b", first, git_branch="stale")
    assert store.publish_session_git_metadata("s", "/a", latest, git_branch="current")
    assert store.get_session("s")["git_branch"] == "current"


def test_model_patch_preserves_markers_and_frozen_snapshot(store):
    store.create_session("s", source="cli", model="first", model_config={"_branched_from": "p", "remove": 1},
                         system_prompt="exact prompt")
    store.patch_session_model_config("s", {"remove": None, "new": 2})
    store.update_session_model("s", "second", provider="provider-b", base_url="https://b.invalid")
    row = store.get_session("s")
    assert row["system_prompt"] == "exact prompt"
    config = json.loads(row["model_config"])
    assert config["_branched_from"] == "p"
    assert "remove" not in config
    assert config["new"] == 2
    assert config["provider"] == "provider-b"


def test_topic_modes_bindings_and_last_binding_disable(store):
    store.create_session("s", source="telegram")
    assert not store.is_telegram_topic_mode_enabled(chat_id="c", user_id="u")
    store.enable_telegram_topic_mode(chat_id="c", user_id="u")
    store.bind_telegram_topic(chat_id="c", thread_id="t", user_id="u", session_key="route", session_id="s")
    assert store.get_telegram_topic_binding(chat_id="c", thread_id="t")["session_id"] == "s"
    assert store.is_telegram_session_linked_to_topic(session_id="s")
    with pytest.raises(ValueError):
        store.bind_telegram_topic(chat_id="c", thread_id="other", user_id="u", session_key="route", session_id="s")
    assert store.delete_telegram_topic_binding(chat_id="c", thread_id="t") == 1
    assert not store.is_telegram_topic_mode_enabled(chat_id="c", user_id="u")


def test_profile_inheritance_does_not_cross_agent_key_namespaces(store):
    store.create_session("p", source="telegram", profile_name="named", session_key="agent:private:chat", cwd="/work")
    store.create_session("child", source="cli", parent_session_id="p", session_key="agent:main:chat")
    assert store.get_session("child")["profile_name"] is None
    assert store.get_session("child")["cwd"] == "/work"


def test_surface_stamping_reaches_compression_ancestors(store):
    store.create_session("p", source="local")
    store.end_session("p", "compression")
    store.create_session("tip", source="cli", parent_session_id="p")
    assert store.get_session("p")["created_source"] == "cli"


def test_title_can_transfer_forward_in_compression_but_not_backwards(store):
    store.create_session("p", source="cli")
    store.set_session_title("p", "title")
    store.end_session("p", "compression")
    store.create_session("tip", source="cli", parent_session_id="p")
    assert store.set_session_title("tip", "title")
    assert store.get_session_title("p") is None
    with pytest.raises(ValueError):
        store.set_session_title("p", "title")
