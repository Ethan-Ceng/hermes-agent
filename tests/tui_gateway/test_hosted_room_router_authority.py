"""An old coordinator's prepared model answer cannot impersonate its successor."""

from gateway import hosted_rooms as rooms, hosted_room_discussion as discussion
from gateway.hosted_room_context import room_context
from tests.tui_gateway.test_hosted_room_router import _service, _room, ROOM_ID, PROFILES


def test_router_answer_is_fenced_by_captured_authority(tmp_path):
    service = _service(tmp_path)
    _room(service)
    binding = service.bindings()[0]
    rooms.append_event(service.db_path, room_id=ROOM_ID, event_id="source", kind="message.user", actor={"kind": "user", "id": "alice"},
        payload={"text": "Fix CI", "thread_id": "thread"}, authority_gateway_id=binding.gateway_id, authority_epoch=binding.authority_epoch)
    room = service._room(ROOM_ID)
    snapshot = service._policy_snapshot(room)
    asked = discussion.plan_next_task(room, list(snapshot.events), local_profiles=PROFILES, initial_watermarks=snapshot.watermarks,
        freeze_input_context=True, room_context=room_context(service.db_path, room_id=ROOM_ID))
    assert asked.status == "route"
    rooms.claim_authority(service.db_path, room_id=ROOM_ID, expected_gateway_id=binding.gateway_id, expected_epoch=binding.authority_epoch,
        new_gateway_id="successor", event_id="claim")
    service._record_route(binding, asked, ("build",))
    assert not any(event["kind"] == "room.routed" for event in rooms.read_events(service.db_path, room_id=ROOM_ID)["events"])
