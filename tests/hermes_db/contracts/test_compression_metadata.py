"""Durable anti-thrash state and conservative lineage recovery."""

import time

import pytest


def test_compression_cooldown_merge_restore_and_numeric_state(store):
    store.create_session("s", "test")
    empty = {"session_exists": True, "cooldown_until": None, "error": None}
    assert store.get_compression_failure_cooldown_row("s") == empty
    deadline = time.time() + 300
    store.record_compression_failure_cooldown("s", deadline, "first")
    store.record_compression_failure_cooldown("s", deadline - 100, "last\x00error")
    row = store.get_compression_failure_cooldown_row("s")
    assert row == {"session_exists": True, "cooldown_until": deadline, "error": "last\x00error"}
    assert store.get_compression_failure_cooldown("s")["error"] == "last\x00error"
    store.restore_compression_failure_cooldown_row("s", empty)
    assert store.get_compression_failure_cooldown("s") is None
    for family in ("fallback_streak", "ineffective_count", "overload_streak", "recovery_deadline"):
        getter, setter = getattr(store, "get_compression_" + family), getattr(store, "set_compression_" + family)
        assert getter("s") == 0
        setter("s", 3)
        assert getter("s") == 3
        setter("s", -1)
        assert getter("s") == 0
    assert store.increment_compression_overload_streak("s") == 1
    assert store.increment_compression_overload_streak("absent") is None
    store.restore_compression_failure_cooldown_row("absent", empty)
    with pytest.raises(RuntimeError):
        store.restore_compression_failure_cooldown_row("s", {"session_exists": False})


def test_compression_orphan_recovery_retires_expired_lock_and_never_live_child(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store.create_session("p", "test")
    store.end_session("p", "compression")
    assert store.try_acquire_compression_lock("p", "owner", ttl_seconds=5)
    assert not store.reopen_orphaned_compression_session("p")
    clock[0] += 6
    assert store.reopen_orphaned_compression_session("p")
    assert not store.refresh_compression_lock("p", "owner")
    assert store.get_session("p")["end_reason"] is None
    store.end_session("p", "compression")
    store.create_session("child", "test", parent_session_id="p")
    assert store.find_live_compression_child("p")["id"] == "child"
    assert not store.reopen_orphaned_compression_session("p")
    assert store.get_compression_lineage("child") == ["p", "child"]


def test_host_explicit_reopen_excludes_automatic_and_reset_boundaries(store):
    store.create_session("s", "test")
    store.end_session("s", "cli_close")
    assert store.reopen_if_explicitly_closed("s", provenance="owned route") == "cli_close"
    for reason in ("ws_disconnect", "session_reset", "compression"):
        store.reopen_session("s")
        store.end_session("s", reason)
        assert store.reopen_if_explicitly_closed("s", provenance="owned route") is None
        assert store.get_session("s")["end_reason"] == reason


def test_only_old_unserved_compression_children_are_finalized(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store.create_session("p", "test")
    store.end_session("p", "compression")
    for child in ("orphan", "served"):
        store.create_session(child, "test", parent_session_id="p")
        store.append_message(child, "user", "durable")
    store.update_token_counts("served", api_call_count=1)
    clock[0] += 8 * 86400
    assert store.finalize_orphaned_compression_sessions() == 1
    assert store.get_session("orphan")["end_reason"] == "orphaned_compression"
    assert store.get_session("served")["ended_at"] is None
    assert store.finalize_orphaned_compression_sessions() == 0
