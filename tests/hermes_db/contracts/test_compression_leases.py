"""Lease fencing shared by native SQLite and the scoped Core backend."""

import time

import pytest


def test_expired_unclaimed_lease_can_renew_but_taken_lease_cannot(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store.create_session("s", "test")
    assert store.try_acquire_compression_lock("s", "first", ttl_seconds=5)
    clock[0] += 6
    assert store.refresh_compression_lock("s", "first", ttl_seconds=5)
    assert not store.try_acquire_compression_lock("s", "second", ttl_seconds=5)
    clock[0] += 6
    assert store.try_acquire_compression_lock("s", "second", ttl_seconds=5)
    assert not store.refresh_compression_lock("s", "first", ttl_seconds=5)
    store.release_compression_lock("s", "first")
    assert store.get_compression_lock_holder("s") == "second"
    assert store.try_acquire_session_turn_lease("s", "first", ttl_seconds=5)
    clock[0] += 6
    assert store.refresh_session_turn_lease("s", "first", ttl_seconds=5)
    assert store.session_turn_lease_expires_at("s", "first") == clock[0] + 5
    clock[0] += 6
    assert store.try_acquire_session_turn_lease("s", "second", ttl_seconds=5)
    assert not store.refresh_session_turn_lease("s", "first", ttl_seconds=5)
    store.release_session_turn_lease("s", "first")
    assert store.session_turn_lease_expires_at("s", "second") == clock[0] + 5


def test_turn_lease_follows_compression_but_excludes_explicit_forks(store):
    store.create_session("root", "test")
    store.end_session("root", "compression")
    store.create_session("child", "test", parent_session_id="root")
    store.create_session("fork", "test", parent_session_id="root", model_config={"_branched_from": "root"})
    store.create_session("reset", "test", parent_session_id="root", model_config={"_reset_from": "root"})
    assert store.try_acquire_session_turn_lease("root", "owner")
    assert not store.try_acquire_session_turn_lease("child", "other")
    assert store.try_acquire_session_turn_lease("fork", "other")
    assert store.try_acquire_session_turn_lease("reset", "other")
    assert store.refresh_session_turn_lease("child", "owner")
    store.release_session_turn_lease("child", "owner")
    assert store.try_acquire_session_turn_lease("root", "replacement")


def test_turn_wait_calls_owner_callbacks_between_transactions(store):
    store.create_session("s", "test")
    assert store.try_acquire_session_turn_lease("s", "first")
    notices = []

    def release_on_notice(elapsed):
        notices.append(elapsed)
        store.release_session_turn_lease("s", "first")

    assert store.acquire_session_turn_lease("s", "second", wait_seconds=2,
        poll_interval_seconds=0.01, on_wait=release_on_notice)
    assert len(notices) == 1
    assert not store.acquire_session_turn_lease("s", "third", should_abort=lambda: True)


def test_core_never_infers_remote_holder_death_from_local_pid(core_pair):
    first, other_store = core_pair
    holder = "instance=remote:pid=999999999:turn=foreign"
    for store in core_pair:
        store.create_session("s", "test")
    assert first.try_acquire_compression_lock("s", holder)
    assert not first.try_acquire_compression_lock("s", "local")
    assert first.try_acquire_session_turn_lease("s", holder)
    assert not first.try_acquire_session_turn_lease("s", "local")
    assert other_store.try_acquire_compression_lock("s", "local")
    assert other_store.try_acquire_session_turn_lease("s", "local")


def test_turn_write_rejects_displaced_holder(store):
    from hermes_state_errors import SessionTurnLeaseLostError

    store.create_session("s", "test")
    assert store.try_acquire_session_turn_lease("s", "owner")
    with pytest.raises(SessionTurnLeaseLostError):
        store.append_message("s", "user", "stale", turn_lease_holder="other")
    assert store.message_count("s") == 0
    store.append_message("s", "user", "owned", turn_lease_holder="owner")
    assert store.message_count("s") == 1
