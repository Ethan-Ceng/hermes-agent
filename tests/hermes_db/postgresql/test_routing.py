"""Routing and bookkeeping contracts on a real isolated PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.hermes_db.contracts import test_gateway_peers as peers
from tests.hermes_db.contracts import test_gateway_rekey as rekey
from tests.hermes_db.contracts import test_routing as routing

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [routing.test_route_replacement_and_retirement_preserve_other_namespaces,
    routing.test_heartbeat_upsert_prune_and_hygiene_are_durable,
    routing.test_handoff_claim_cas_failure_and_restart_reclaim,
    routing.test_reset_generation_is_monotonic_and_separate_from_compression,
    peers.test_peer_record_self_heals_and_repoints_compression_ancestors,
    peers.test_orphan_lineage_adoption_keeps_non_null_peer_fields_and_closes_donor,
    rekey.test_profile_rekey_changes_exact_identity_and_literal_namespace,
    rekey.test_profile_rekey_collision_rolls_back_all_identity_changes,
    rekey.test_profile_rekey_moves_current_topic_identity_and_binding_namespace,
    rekey.test_profile_rekey_topic_collision_preserves_session_owner]
CLOCK_CONTRACTS = [peers.test_peer_recovery_does_not_reach_behind_reset_boundary,
    peers.test_never_active_selector_protects_user_keep_intent_and_any_history,
    peers.test_orphan_time_window_ambiguity_never_guesses_a_peer,
    routing.test_expiring_route_fences_age_out_but_never_shorten_permanent_fences]
PAIR_CONTRACTS = [routing.test_core_routes_heartbeats_hygiene_and_handoffs_never_cross_store,
    peers.test_core_messaging_takeover_settles_local_receipt_history_and_title,
    rekey.test_core_profile_rekey_never_treats_another_store_as_collision,
    rekey.test_core_profile_rekey_delivery_rows_stay_in_own_store]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_routing_on_postgresql(pg_store, contract):
    contract(pg_store)


@pytest.mark.parametrize("contract", CLOCK_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_clock_routing_on_postgresql(pg_store, monkeypatch, contract):
    contract(pg_store, monkeypatch)


@pytest.mark.parametrize("contract", PAIR_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_scoped_routing_on_postgresql(pg_pair, contract):
    contract(pg_pair)


def test_handoff_requests_and_claims_choose_one_owner(pg_store):
    pg_store.create_session("s", "cli")

    def compete(action):
        gate = Barrier(2)

        def invoke():
            gate.wait(15)
            return action()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            return sorted(future.result(20) for future in futures)

    assert compete(lambda: pg_store.request_handoff("s", "telegram")) == [False, True]
    assert compete(lambda: pg_store.claim_handoff("s")) == [False, True]


def test_hygiene_increments_do_not_lose_updates(pg_store):
    gate = Barrier(4)

    def increment():
        gate.wait(15)
        return pg_store.increment_hygiene_failure_streak("key_%")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(increment) for _ in range(4)]
        assert sorted(future.result(20) for future in futures) == [1, 2, 3, 4]


def test_stale_route_snapshot_cannot_restore_retired_route(pg_store):
    key, entry = "agent:secondary:chat", '{"session_id":"retired"}'
    pg_store.save_gateway_routing_entry(key, entry, scope="lanes")
    gate = Barrier(2)

    def replace():
        gate.wait(15)
        pg_store.replace_gateway_routing_entries({key: entry}, scope="lanes")

    def retire():
        gate.wait(15)
        pg_store.retire_gateway_routes(["retired"], namespace="secondary")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(replace), pool.submit(retire)]
        for future in futures:
            future.result(20)
    assert pg_store.load_gateway_routing_entries(scope="lanes") == {}
