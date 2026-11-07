"""Persisted capacities, transcript bounds and immutable context settings on PG."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_context import room_context, set_room_context
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint, MAX_THREAD_TRANSCRIPT_EVENTS
from tests.hermes_db.postgresql.test_room_policy import create, append

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_transcript_bound_and_capacity_survive_reopen(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        for index in range(MAX_THREAD_TRANSCRIPT_EVENTS + 2):
            append(location, f"source-{index}", "message.user", dict(thread_id="thread", text=str(index)))
        checkpoint = HostedRoomPolicyCheckpoint(location, max_active_events=80)
        saved = checkpoint.snapshot(room_id="room", latest_seq=MAX_THREAD_TRANSCRIPT_EVENTS + 2)
        assert len(saved.events) == MAX_THREAD_TRANSCRIPT_EVENTS
        assert saved.events[0]["event_id"] == "source-2"
        assert HostedRoomPolicyCheckpoint(location).max_active_events == 80
        assert HostedRoomPolicyCheckpoint(location).snapshot(room_id="room", latest_seq=saved.through_seq) == saved


def test_context_retry_uses_first_write_schema_and_routing(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        rooms.create_room(location, room_id="room", name="Context", members=[dict(member_id="ops", profile="ops", handle="ops")],
            authority_gateway_id=rooms.local_authority_gateway_id())
        first = set_room_context(location, room_id="room", event_id="first", purpose="Ship", notes="中文\x00🙂", routing="lead", lead_member_id="ops")
        second = set_room_context(location, room_id="room", event_id="second", purpose="Later", notes="", routing="auto")
        replay = set_room_context(location, room_id="room", event_id="first", purpose="Ship", notes="中文\x00🙂")
        assert replay["event"]["idempotent"] and replay["context"] == first["context"]
        assert room_context(location, room_id="room") == second["context"]
        assert room_context(location, room_id="room", before_seq=second["event"]["seq"]) == first["context"]
        with pytest.raises(rooms.EventConflictError):
            set_room_context(location, room_id="room", event_id="first", purpose="different", notes="")
        assert rooms.read_events(location, room_id="room")["latest_seq"] == 2


def test_active_projection_overflow_is_rejected_without_losing_cursor(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        append(location, "source", "message.user", dict(thread_id="thread", text="hello"))
        checkpoint = HostedRoomPolicyCheckpoint(location)
        for index in range(checkpoint.max_active_events - 1):
            append(location, f"assignment-{index}", "room.assignment", dict(thread_id="thread", discussion_event_id="source"))
        assert len(checkpoint.snapshot(room_id="room", latest_seq=checkpoint.max_active_events).events) == checkpoint.max_active_events
        last = append(location, "overflow", "room.assignment", dict(thread_id="thread", discussion_event_id="source"))
        with pytest.raises(RuntimeError, match="exceeded its bound"):
            checkpoint.snapshot(room_id="room", latest_seq=last["seq"])
        # The visible canonical log and its durable projection cursor remain intact.
        assert checkpoint.sync(room_id="room", latest_seq=last["seq"]) == last["seq"]
        assert rooms.read_events(location, room_id="room")["latest_seq"] == last["seq"]
