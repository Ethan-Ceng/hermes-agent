"""Sweep fences expire only when they do not hold a durable derived identity."""

import time

import pytest

from hermes_state_runtime import RuntimeStoreError


def _prune(store):
    from hermes_state import SessionDB
    if isinstance(store, SessionDB):
        from hermes_state_mutation_retirement import prune_retired_tombstones
        store._execute_write(prune_retired_tombstones)
    else:
        store.prune_retired_tombstones()


def test_empty_sweep_skips_pending_work_and_expires_only_non_derived_fences(store, runtime, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    for sid, source in [("ordinary", "cli"), ("derived", "bot_room"), ("busy", "cli"), ("permanent", "cli")]:
        store.create_session(sid, source)
        store.end_session(sid, "done")
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="human", session_id="busy", request_id="r", payload={})
    store.delete_session("permanent")
    assert store.delete_empty_sessions() == 2
    assert store.get_session("busy") is not None
    monkeypatch.setattr(time, "time", lambda: 1000000.0 + 8 * 86400)
    _prune(store)
    store.create_session("ordinary", "cli")
    for sid in ("derived", "permanent"):
        with pytest.raises(RuntimeStoreError, match="not_found"):
            store.create_session(sid, "cli")


def test_delete_empty_is_atomic_and_never_discards_a_leased_first_turn(store):
    store.create_session("s", "cli")
    store.try_acquire_session_turn_lease("s", "holder")
    assert not store.delete_session_if_empty("s")
    store.release_session_turn_lease("s", "holder")
    store.create_session("child", "cli", parent_session_id="s")
    assert not store.delete_session_if_empty("s")
    store.discard_unadmitted_session("child")
    store.append_message("s", "user", "history")
    assert not store.delete_session_if_empty("s")
    store.create_session("empty", "cli")
    assert store.delete_session_if_empty("empty")


def test_discard_unadmitted_allows_seed_retry_but_terminal_receipts_require_fence(store, runtime):
    store.create_session("s", "cli")
    store.append_message("s", "user", "seed")
    assert store.discard_unadmitted_session("s")
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={})
    row = runtime.admit_input(**args)
    runtime.cancel_input(epoch=epoch, admission_id=row["admission_id"])
    assert store.discard_unadmitted_session("s")
    assert runtime.admit_input(**args)["status"] == "terminal"
    with pytest.raises(RuntimeStoreError, match="not_found"):
        store.create_session("s", "cli")


def test_never_active_sweep_keeps_leased_candidates_and_counts_only_removed_routes(store, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    for sid in ("idle", "leased"):
        store.create_session(sid, "telegram", session_key="agent:old:" + sid)
        store.save_gateway_routing_entry("agent:old:" + sid, '{"session_id":"' + sid + '"}')
    store.try_acquire_session_turn_lease("leased", "holder", ttl_seconds=864000)
    monkeypatch.setattr(time, "time", lambda: 1000000.0 + 3 * 86400)
    removed = []
    assert store.prune_never_active_keyed_sessions(older_than_days=2, deleted_ids=removed) == (1, 1, 1)
    assert removed == ["idle"] and store.get_session("leased") is not None
    assert set(store.load_gateway_routing_entries()) == {"agent:old:leased"}


def test_core_derived_generation_walk_keeps_passed_expiring_fences(core_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect

    store, other = core_pair
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    derive = lambda generation: f"derived-{generation}"
    for sid in (derive(0), derive(1)):
        store.create_session(sid, "cli")
        assert store.delete_session_if_empty(sid)
    assert store.first_generation(derive) == (2, derive(2))
    assert store.first_generation(derive, pinned=CoreEffect(lambda conn, scope, sid: sid == derive(0))) == (0, derive(0))
    assert not store.keep_passed_fences(derive, derive(3))
    assert store.keep_passed_fences(derive, derive(2))
    monkeypatch.setattr(time, "time", lambda: 1000000.0 + 8 * 86400)
    store.prune_retired_tombstones()
    assert store.first_generation(derive) == (2, derive(2)) and other.first_generation(derive) == (0, derive(0))


def test_core_empty_sweep_keeps_closed_ancestor_while_descendant_holds_root_lease(core_pair):
    store, _ = core_pair
    store.create_session("root", "cli")
    store.end_session("root", "compression")
    store.create_session("child", "cli", parent_session_id="root")
    store.append_message("child", "user", "live")
    assert store.try_acquire_session_turn_lease("child", "holder")
    assert store.delete_empty_sessions() == 0
    assert store.get_session("root") is not None
    assert store.get_compression_lineage("child") == ["root", "child"]
    assert not store.try_acquire_session_turn_lease("root", "other")
    store.release_session_turn_lease("child", "holder")
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
    runtime = PostgresRuntimeStore(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.register_worker(epoch=epoch, execution_id="worker", session_id="child", generation=0,
        kind="compute", adoption_secret="private")
    assert store.delete_empty_sessions() == 0
    runtime.mutate_worker(epoch=epoch, execution_id="worker", session_id="child", generation=0, sequence=1,
        operation="execution.finish", payload={})
    assert store.delete_empty_sessions() == 1
