"""Bounded room projections use real PG state and preserve opaque JSON identities."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from tui_gateway.hosted_room_router_call import RouterCalls, CLAIM_TTL_SECONDS

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def create(location):
    rooms.create_room(location, room_id="room", name="Room", members=[{"profile": "ops", "handle": "ops"}], authority_gateway_id="owner")


def append(location, event_id, kind, payload):
    actor_kind = {"message.user": "user", "message.member": "member"}.get(kind, "gateway")
    return rooms.append_event(location, room_id="room", event_id=event_id, kind=kind,
        actor={"kind": actor_kind, "id": "ops" if actor_kind == "member" else "owner"}, payload=payload,
        authority_gateway_id="owner", authority_epoch=1)


def test_policy_snapshot_reopen_exact_watermarks_and_opaque_thread(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        thread = "讨论\x00🙂"
        first = append(location, "source", "message.user", {"text": "question", "thread_id": thread})
        checkpoint = HostedRoomPolicyCheckpoint(location)
        initial = checkpoint.snapshot(room_id="room", latest_seq=first["seq"])
        assert initial.events[0]["payload"]["thread_id"] == thread
        terminal = append(location, "terminal", "turn.failed", dict(thread_id=thread, discussion_event_id="source",
            member_id="ops\x00🙂", seen_through_seq=1, task_id="opaque\x00🙂", zero=0, false=False))
        saved = checkpoint.snapshot(room_id="room", latest_seq=terminal["seq"])
        assert saved.watermarks == {(thread, "ops\x00🙂"): 1}
        assert checkpoint.publication_exists(room_id="room", task_id="opaque\x00🙂", status="failed", execution_generation=1)
        assert HostedRoomPolicyCheckpoint(location).snapshot(room_id="room", latest_seq=terminal["seq"]) == saved
    with pg_profiles("two"):
        other = rooms.default_db_path()
        create(other)
        assert HostedRoomPolicyCheckpoint(other).snapshot(room_id="room", latest_seq=0).events == ()


def test_router_claims_persist_expire_and_stale_owner_cannot_release_successor(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        now = [100.0]
        first = RouterCalls(location, clock=lambda: now[0])
        second = RouterCalls(location, clock=lambda: now[0])
        key = ("room", "opaque\x00🙂")
        assert first._claim(key)
        assert not second._claim(key)
        now[0] += CLAIM_TTL_SECONDS + 1
        assert second._claim(key)
        first._release(key)
        assert not RouterCalls(location, clock=lambda: now[0])._claim(key)
        second._release(key)
        assert first._claim(key)


def test_continue_reopens_projection_and_late_outcomes_keep_transcript(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        first = append(location, "source", "message.user", {"text": "first", "thread_id": "thread"})
        append(location, "deferred", "turn.deferred", dict(thread_id="thread", discussion_event_id="source", task_id="task", execution_generation=5))
        capped = append(location, "cap", "room.activity", dict(thread_id="thread", discussion_event_id="source", status="bounded"))
        checkpoint = HostedRoomPolicyCheckpoint(location)
        assert checkpoint.snapshot(room_id="room", latest_seq=capped["seq"]).events == ()
        continued = append(location, "continue", "room.continued", dict(thread_id="thread", discussion_event_id="source", grant=1))
        reopened = checkpoint.snapshot(room_id="room", latest_seq=continued["seq"])
        assert [event["kind"] for event in reopened.events] == ["message.user", "turn.deferred", "room.continued"]
        assert checkpoint.publication_exists(room_id="room", task_id="task", status="deferred", execution_generation=5)
        assert not checkpoint.publication_exists(room_id="room", task_id="task", status="deferred", execution_generation=6)
        message = append(location, "dmessage:task", "message.member", dict(thread_id="thread", discussion_event_id="source", task_id="dtask:task", member_id="ops", text="committed reply"))
        append(location, "done", "room.activity", dict(thread_id="thread", discussion_event_id="source", status="settled"))
        newer = append(location, "newer", "message.user", dict(thread_id="thread", text="next"))
        terminal = append(location, "dterminal:task", "turn.settled", dict(thread_id="thread", discussion_event_id="source", task_id="dtask:task",
            member_id="ops", seen_through_seq=first["seq"], message_event_id=message["event_id"]))
        saved = checkpoint.snapshot(room_id="room", latest_seq=terminal["seq"])
        assert saved.watermarks == {("thread", "ops"): message["seq"]}
        assert any(event["event_id"] == message["event_id"] for event in saved.events)
        frozen = checkpoint.events_for_task(room_id="room", source_event_seq=first["seq"], input_context={"watermark": 0, "event_seqs": [first["seq"]]}, task_id="dtask:task")
        assert {event["seq"] for event in frozen} == {first["seq"], message["seq"], newer["seq"], terminal["seq"]}


def test_concurrent_replay_claim_and_derived_cache_rebuild_are_scoped(pg_profiles):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import update
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.tables.room_policy import transcript_state
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        for index in range(4):
            append(location, f"input-{index}", "message.user", {"text": str(index), "thread_id": "thread"})
        first, second = HostedRoomPolicyCheckpoint(location), HostedRoomPolicyCheckpoint(location)
        gate = Barrier(2)
        def sync(checkpoint):
            gate.wait(15)
            return checkpoint.snapshot(room_id="room", latest_seq=4)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(sync, checkpoint) for checkpoint in (first, second)]
            snapshots = [future.result(30) for future in futures]
        assert snapshots[0] == snapshots[1]
        assert len(snapshots[0].events) == 4
        with acquire_profile_domain("rooms") as store, store.write() as conn:
            conn.execute(update(transcript_state).where(transcript_state.c.store_id == "one").values(schema_version=2))
        assert HostedRoomPolicyCheckpoint(location).snapshot(room_id="room", latest_seq=4) == snapshots[0]
        contenders = [RouterCalls(location), RouterCalls(location)]
        gate = Barrier(2)
        def claim(router):
            gate.wait(15)
            return router._claim(("room", "source"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, router) for router in contenders]
            claimed = [future.result(30) for future in futures]
        assert sorted(claimed) == [False, True]
