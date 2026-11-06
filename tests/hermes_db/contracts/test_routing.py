"""Routing namespaces, durable liveness and handoff state contracts."""

import json
import time


def test_route_replacement_and_retirement_preserve_other_namespaces(store):
    entry = lambda sid: json.dumps({"session_id": sid, "metadata": "keep\u0000exact"})
    store.save_gateway_routing_entry("agent:secondary:chat", entry("gone"), scope="lanes")
    store.save_gateway_routing_entry("main-chat", entry("gone"), scope="other")
    store.retire_gateway_routes(["gone"], namespace="secondary")
    assert store.load_gateway_routing_entries(scope="lanes") == {}
    assert store.load_gateway_routing_entries(scope="other") == {}
    rejected = store.replace_gateway_routing_entries({"agent:secondary:chat": entry("gone"), "alive": entry("live")}, scope="lanes")
    assert rejected == {"agent:secondary:chat"}
    assert store.load_gateway_routing_entries(scope="lanes") == {"alive": entry("live")}
    store.create_session("gone", "cli")
    store.save_gateway_routing_entry("main-chat", entry("gone"), scope="other")
    assert store.gateway_routing_entry_for_session("gone")["session_id"] == "gone"
    store.replace_gateway_routing_entries({}, scope="lanes")
    assert store.load_gateway_routing_entries(scope="lanes") == {}
    assert store.load_gateway_routing_entries(scope="other") == {"main-chat": entry("gone")}


def test_heartbeat_upsert_prune_and_hygiene_are_durable(store):
    now = time.time()
    store.register_backend_heartbeat(backend_id="same", pid=10, started_at=now - 30, last_heartbeat=now - 20,
                                     profile="profile", host="remote")
    store.register_backend_heartbeat(backend_id="same", pid=11, started_at=now - 10, last_heartbeat=now)
    rows = store.list_backend_heartbeats()
    assert len(rows) == 1 and rows[0]["pid"] == 11 and rows[0]["started_at"] == now - 10
    assert store.prune_stale_heartbeats(max_age_seconds=60) == []
    store.register_backend_heartbeat(backend_id="old", pid=99, started_at=now - 100, last_heartbeat=now - 100)
    assert store.prune_stale_heartbeats(max_age_seconds=60) == ["old"]
    assert store.clear_backend_heartbeat("same") and not store.clear_backend_heartbeat("same")
    assert [store.increment_hygiene_failure_streak("chat_%") for _ in range(3)] == [1, 2, 3]
    store.reset_hygiene_failure_streak("chat_%")
    assert store.increment_hygiene_failure_streak("chat_%") == 1


def test_handoff_claim_cas_failure_and_restart_reclaim(store):
    store.create_session("s", "cli")
    assert store.request_handoff("s", "telegram")
    assert not store.request_handoff("s", "discord")
    assert store.has_pending_handoffs() and [row["id"] for row in store.list_pending_handoffs()] == ["s"]
    assert store.claim_handoff("s") and not store.claim_handoff("s")
    assert not store.fail_handoff("s", "waiter", only_states=("pending",))
    assert store.get_handoff_state("s") == {"state": "running", "platform": "telegram", "error": None}
    assert store.reclaim_stale_running_handoffs("owner restarted\x00") == ["s"]
    assert store.get_handoff_state("s")["error"] == "owner restarted\x00"
    assert store.request_handoff("s", "discord")
    assert store.fail_handoff("s", "x" * 600, only_states=("pending",))
    assert len(store.get_handoff_state("s")["error"]) == 500
    store.complete_handoff("s")
    assert store.get_handoff_state("s") == {"state": "completed", "platform": "discord", "error": None}
    assert not store.has_pending_handoffs()


def test_core_routes_heartbeats_hygiene_and_handoffs_never_cross_store(core_pair):
    first, second = core_pair
    for store in core_pair:
        store.create_session("s", "cli")
        store.save_gateway_routing_entry("route", '{"session_id":"s"}')
        store.register_backend_heartbeat(backend_id="backend", pid=1, started_at=1)
    first.retire_gateway_routes(["s"], namespace="main")
    first.clear_backend_heartbeat("backend")
    assert second.load_gateway_routing_entries() == {"route": '{"session_id":"s"}'}
    assert len(second.list_backend_heartbeats()) == 1
    first.increment_hygiene_failure_streak("route")
    assert second.increment_hygiene_failure_streak("route") == 1
    assert first.request_handoff("s", "telegram")
    assert not second.has_pending_handoffs()


def test_reset_generation_is_monotonic_and_separate_from_compression(store):
    store.create_session("s", "telegram", session_key="route")
    assert store.latest_conversation_boundary("route", "telegram") is None
    store.end_session("s", "session_reset")
    store.end_session("s", "session_reset")
    assert store.latest_conversation_boundary("route", "telegram") == 1
    store.reopen_session("s")
    store.end_session("s", "compression")
    assert store.latest_conversation_boundary("route", "telegram") == 1
    store.create_session("c", "telegram", parent_session_id="s")
    store.end_session("c", "session_reset")
    assert store.latest_conversation_boundary("route", "telegram") == 2
    assert store.latest_conversation_boundary("route", "api_server") is None
    store.create_session("trim", " telegram ", session_key=" route ")
    store.end_session("trim", "session_reset")
    assert store.latest_conversation_boundary("route", "telegram") == 3


def test_expiring_route_fences_age_out_but_never_shorten_permanent_fences(store, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    key, entry = "agent:secondary:chat", '{"session_id":"gone"}'
    store.retire_gateway_routes(["gone"], namespace="secondary", expiring=["gone"])
    store.save_gateway_routing_entry(key, entry)
    assert store.load_gateway_routing_entries() == {}
    clock[0] += 8 * 86400
    store.save_gateway_routing_entry(key, entry)
    assert store.load_gateway_routing_entries() == {key: entry}
    store.retire_gateway_routes(["gone"], namespace="secondary")
    store.retire_gateway_routes(["gone"], namespace="secondary", expiring=["gone"])
    clock[0] += 8 * 86400
    store.save_gateway_routing_entry(key, entry)
    assert store.load_gateway_routing_entries() == {}
