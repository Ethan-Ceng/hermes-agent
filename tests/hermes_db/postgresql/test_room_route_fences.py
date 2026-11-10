"""Canonical PG service discards router answers whose captured lineage is stale."""

from contextlib import closing
from types import SimpleNamespace

import pytest

from gateway import hosted_rooms as rooms, hosted_room_discussion as discussion
from gateway.hosted_room_context import set_room_context, room_context
from gateway.session_hosted_service import CanonicalHostedRoomService
from hermes_cli.db_sessions import open_session_store
from hermes_db.integration.runtime_access import runtime_for_store

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def prepared(db, home):
    authority = SimpleNamespace(db=db, profile_id=str(home), epoch=runtime_for_store(db).begin_epoch(instance_id="owner"))
    service = CanonicalHostedRoomService(authority, None)
    service.local_profiles = lambda: ("research", "build", "review")
    service.create_room(room_id="room", name="Router", members=[dict(member_id=name, profile=name, handle=name) for name in service.local_profiles()],
        admit=service._coordination.owner_effect("alice", "room"))
    set_room_context(service.db_path, room_id="room", event_id="settings", purpose="Ship", notes="", routing="auto")
    binding = service.bindings()[0]
    rooms.append_event(service.db_path, room_id="room", event_id="source", kind="message.user", actor={"kind": "user", "id": "alice"},
        payload={"text": "Fix the build", "thread_id": "thread"}, authority_gateway_id=binding.gateway_id, authority_epoch=binding.authority_epoch)
    room = service._room("room")
    snapshot = service._policy_snapshot(room)
    asked = discussion.plan_next_task(room, list(snapshot.events), local_profiles=service.local_profiles(), initial_watermarks=snapshot.watermarks,
        freeze_input_context=True, room_context=room_context(service.db_path, room_id="room"))
    assert asked.status == "route"
    return service, binding, asked


def test_authority_change_during_model_call_rejects_old_router_answer(pg_profiles):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        service, binding, asked = prepared(db, home)
        rooms.claim_authority(service.db_path, room_id="room", expected_gateway_id=binding.gateway_id, expected_epoch=1,
            new_gateway_id="successor", event_id="claim")
        service._record_route(binding, asked, ("build",))
        assert not any(event["kind"] == "room.routed" for event in rooms.read_events(service.db_path, room_id="room")["events"])


@pytest.mark.parametrize("interruption", ["none", "stop", "new_message", "other_worker"])
def test_router_preparation_rechecks_log_before_recording(pg_profiles, interruption):
    from gateway import hosted_room_router as router
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        service, binding, asked = prepared(db, home)
        if interruption == "stop":
            rooms.request_room_stop(service.db_path, room_id="room", cancel_id="stop", expected_gateway_id=binding.gateway_id, expected_epoch=1)
        elif interruption == "new_message":
            rooms.append_event(service.db_path, room_id="room", event_id="newer", kind="message.user", actor={"kind": "user", "id": "alice"},
                payload={"text": "new request", "thread_id": "thread"}, authority_gateway_id=binding.gateway_id, authority_epoch=1)
        elif interruption == "other_worker":
            rooms.append_event(service.db_path, room_id="room", event_id=router.routed_event_id(asked.discussion_event_id), kind="room.routed",
                actor={"kind": "gateway", "id": binding.gateway_id}, payload=router.routed_payload(discussion_event_id=asked.discussion_event_id,
                    thread_id=asked.thread_id, member_ids=("review",)), authority_gateway_id=binding.gateway_id, authority_epoch=1)
        service._record_route(binding, asked, ("build",))
        routed = [event for event in rooms.read_events(service.db_path, room_id="room")["events"] if event["kind"] == "room.routed"]
        assert len(routed) == (1 if interruption in {"none", "other_worker"} else 0)
        if routed:
            assert routed[0]["payload"]["member_ids"] == (["review"] if interruption == "other_worker" else ["build"])


def test_blocked_model_call_holds_no_pg_connection_and_stop_commits(pg_profiles):
    from threading import Event
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from tests.waiting import wait_until
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        service, binding, asked = prepared(db, home)
        started, release = Event(), Event()
        def model():
            started.set()
            assert release.wait(20)
            return ("build",)
        key = ("room", asked.discussion_event_id)
        assert service._router_calls.start(key, model, lambda picked: service._record_route(binding, asked, picked))
        assert started.wait(15)
        try:
            with acquire_profile_domain("rooms") as store:
                assert get_engine(store.settings.postgresql).pool.checkedout() == 0
            rooms.request_room_stop(service.db_path, room_id="room", cancel_id="stop", expected_gateway_id=binding.gateway_id, expected_epoch=1)
        finally:
            release.set()
            wait_until(lambda: not service._router_calls.inflight(key), what="PG router released its claim")
        assert not any(event["kind"] == "room.routed" for event in rooms.read_events(service.db_path, room_id="room")["events"])
