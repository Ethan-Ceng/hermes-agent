"""Bulk retention is based on activity, preserves pins/open rows and compression tails."""

import time

import pytest

DAY = 86400
NOW = 1800000000.0


def _make(store, sid, *, ended=True, pinned=False):
    store.create_session(sid, "cli")
    store.append_message(sid, "user", sid)
    if ended:
        store.end_session(sid, "done")
    if pinned:
        store.set_session_pinned(sid, True)


def test_retention_selection_spares_open_pinned_and_recent_message(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 120 * DAY)
    for sid in ("old", "recent"):
        _make(store, sid)
    _make(store, "pin", pinned=True)
    _make(store, "open", ended=False)
    monkeypatch.setattr(time, "time", lambda: NOW)
    store.append_message("recent", "assistant", "fresh activity")
    assert {row["id"] for row in store.list_prune_candidates(older_than_days=90)} == {"old"}
    assert store.count_prune_matches(older_than_days=90, pinned_only=True) == 1
    assert store.count_open_prune_matches(older_than_days=90) == 1
    assert store.archive_sessions(older_than_days=90, include_open=True) == 2
    deleted = []
    assert store.prune_sessions(older_than_days=None, archived=True, deleted_ids=deleted) == 1
    assert deleted == ["old"] and store.get_session("open") and store.get_session("pin")


def test_old_compression_ancestor_waits_for_current_continuation(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 120 * DAY)
    _make(store, "root", ended=False)
    store.end_session("root", "compression")
    monkeypatch.setattr(time, "time", lambda: NOW)
    store.create_session("tip", "cli", parent_session_id="root")
    store.append_message("tip", "user", "active continuation")
    assert store.archive_sessions(older_than_days=90) == 0
    assert store.list_prune_candidates(older_than_days=90, whole_lineages=True) == []
    store.end_session("tip", "done")
    monkeypatch.setattr(time, "time", lambda: NOW + 150 * DAY)
    assert {row["id"] for row in store.list_prune_candidates(older_than_days=90, whole_lineages=True)} == {"root", "tip"}
    assert store.prune_sessions(older_than_days=90) == 2


def test_retention_validates_destructive_bounds_and_escapes_literal_filters(store):
    with pytest.raises(ValueError, match="negative|>= 0"):
        store.list_prune_candidates(older_than_days=-1)
    with pytest.raises(ValueError, match="open"):
        store.prune_sessions(older_than_days=None, include_open=True)
    with pytest.raises(TypeError):
        store.list_prune_candidates(misspelled_filter=True)
    _make(store, "literal")
    _make(store, "other")
    store.set_session_title("literal", "100%_literal")
    store.set_session_title("other", "100XXliteral")
    assert [row["id"] for row in store.list_prune_candidates(title_like="%_")] == ["literal"]


def test_auto_archive_is_scoped_throttled_and_preserves_prompt_history(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 120 * DAY)
    store.create_session("stale", "cli", system_prompt="frozen\x00prompt")
    store.append_message("stale", "user", "cached prefix")
    _make(store, "pinned", ended=False, pinned=True)
    _make(store, "canonical", ended=False)
    store.set_session_title("canonical", "Bot Chat")
    store.set_session_hidden("canonical", True)
    before = store.get_messages_as_conversation("stale")
    monkeypatch.setattr(time, "time", lambda: NOW)
    assert store.maybe_auto_archive(idle_days=3) == {"skipped": False, "archived": 1}
    assert store.get_session("stale")["auto_archived"] == 1
    assert not store.get_session("pinned")["archived"] and not store.get_session("canonical")["archived"]
    assert store.get_messages_as_conversation("stale") == before
    assert store.get_session("stale")["system_prompt"] == "frozen\x00prompt"
    assert store.maybe_auto_archive(idle_days=3) == {"skipped": True, "archived": 0}


def test_orphan_sweep_respects_live_heartbeat_and_turn_lease(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 10000)
    store.create_session("orphan", "tui")
    store.append_message("orphan", "user", "history stays")
    monkeypatch.setattr(time, "time", lambda: NOW)
    store.register_backend_heartbeat(backend_id="backend", pid=9999999, started_at=NOW - 10020, last_heartbeat=NOW)
    assert store.sweep_orphaned_sessions(max_idle_seconds=60) == []
    store.clear_backend_heartbeat("backend")
    assert store.acquire_session_turn_lease("orphan", "owner", ttl_seconds=1000)
    assert store.sweep_orphaned_sessions(max_idle_seconds=60) == []
    store.release_session_turn_lease("orphan", "owner")
    assert store.sweep_orphaned_sessions(max_idle_seconds=60) == ["orphan"]
    assert store.get_session("orphan")["end_reason"] == "startup_orphan_reap"
    assert store.get_messages_as_conversation("orphan")[0]["content"] == "history stays"
    assert store.sweep_orphaned_sessions(max_idle_seconds=60) == []


def test_auto_prune_keeps_messaging_open_and_gives_closed_orphan_a_retention_window(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 120 * DAY)
    _make(store, "old")
    store.create_session("job", "cron")
    store.append_message("job", "user", "orphaned job history")
    store.create_session("chat", "telegram")
    store.append_message("chat", "user", "messaging stays open")
    monkeypatch.setattr(time, "time", lambda: NOW)
    result = store.maybe_auto_prune_and_vacuum(retention_days=90, vacuum=False)
    assert result["pruned"] == 1 and result["closed"] == 1 and not result["vacuumed"]
    assert store.get_session("old") is None
    assert store.get_session("job")["end_reason"] == "startup_orphan_reap"
    assert store.get_session("chat")["ended_at"] is None
    assert store.prune_sessions(older_than_days=90) == 0
    assert store.maybe_auto_prune_and_vacuum(retention_days=90, vacuum=False)["skipped"]


def test_core_auto_archive_throttle_does_not_cross_store_boundaries(core_pair, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW - 120 * DAY)
    for store in core_pair:
        _make(store, "same")
    monkeypatch.setattr(time, "time", lambda: NOW)
    assert core_pair[0].maybe_auto_archive()["archived"] == 1
    assert core_pair[0].maybe_auto_archive()["skipped"]
    assert core_pair[1].maybe_auto_archive()["archived"] == 1
