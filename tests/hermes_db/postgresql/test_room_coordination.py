"""Canonical owner and exact task admission share the real PG FIFO transaction."""

from contextlib import closing
from types import SimpleNamespace

import pytest

from gateway import hosted_rooms as rooms
from hermes_db.domains.rooms import rules as room_rules
from gateway import hosted_room_driver as driver
from gateway.session_hosted_storage import RoomCoordination, HostedMemberAuthorization, HostedAdmissionAuthorizer
from gateway.session_hosted_service import probe_native_room_owner
from hermes_cli.db_sessions import open_session_store
from hermes_db.domains.rooms.postgres.ownership import owner, owners
from hermes_db.domains.runtime.access import runtime_for_store
from hermes_state_runtime import RuntimeStoreError
from tui_gateway.hosted_room_driver import HostedRoomBinding

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def coordination(db):
    epoch = runtime_for_store(db).begin_epoch(instance_id="owner")
    return RoomCoordination(SimpleNamespace(db=db, epoch=epoch))


def create(coord, *, subject="alice", room_id="room"):
    return rooms.create_room(coord.path, room_id=room_id, name="Owned", members=[{"member_id": "ops", "profile": "ops", "handle": "ops"}],
        authority_gateway_id="gateway", admit=coord.owner_effect(subject, room_id))


def test_owner_and_room_commit_or_rollback_together_and_are_scoped(pg_profiles, monkeypatch):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        coord = coordination(db)
        with monkeypatch.context() as patch:
            patch.setattr(room_rules, "MAX_ACTIVE_ROOMS", 0)
            with pytest.raises(rooms.HostedRoomError):
                create(coord)
        assert coord.core_read(owner, "room") is None
        assert not probe_native_room_owner(coord.path, room_id="room")
        create(coord)
        assert coord.core_read(owners) == ("room",)
        assert probe_native_room_owner(coord.path, room_id="room")
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            coord.core_authorize("mallory", "room")
    with pg_profiles("two") as home, closing(open_session_store(home / "state.db")) as db:
        other = coordination(db)
        assert other.core_read(owner, "room") is None
        assert not probe_native_room_owner(other.path, room_id="room")


def test_fenced_submit_uses_same_connection_and_rejects_stopped_task(pg_profiles):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        coord = coordination(db)
        create(coord)
        identity = driver.TaskIdentity("room", "task", "thread", "turn")
        driver.admit_task(coord.path, identity, payload={"target_profile": "ops", "prompt": "input", "source_event_seq": 1}, clock=lambda: 10)
        lease = driver.acquire_lease(coord.path, room_id="room", gateway_id="gateway", authority_epoch=1, process_generation="process", ttl_seconds=30, clock=lambda: 10)
        driver.start_task(coord.path, identity, lease, expected_cancel_generation=0, clock=lambda: 10)
        db.create_session("session", "test")
        authorization = HostedMemberAuthorization(coord, available=lambda: True, owner="alice",
            binding=HostedRoomBinding("room", "gateway", 1), member="ops", profile="ops")
        fence = HostedAdmissionAuthorizer(coord, authorization).for_task(identity, 1)
        runtime = runtime_for_store(db)
        args = dict(epoch=coord.authority.epoch, principal_id="alice", session_id="session", request_id="request", payload={"text": "input"})
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            runtime.admit_input(**args, _authorize_write=fence.effect())
        with fence.context():
            admitted = runtime.admit_input(**args, _authorize_write=fence.effect())
        assert admitted["status"] == "queued"
        driver.begin_task_cancel(coord.path, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 10)
        with fence.context():
            with pytest.raises(RuntimeStoreError, match="permission_denied"):
                runtime.admit_input(**(args | {"request_id": "refused"}), _authorize_write=fence.effect())
        assert [row["request_id"] for row in runtime.list_admissions(session_id="session", pending_only=False)] == ["request"]


def test_old_coordination_epoch_is_fenced_before_owner_claim(pg_profiles):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        coord = coordination(db)
        runtime_for_store(db).begin_epoch(instance_id="successor")
        with pytest.raises(RuntimeStoreError, match="stale_epoch"):
            create(coord)
        assert not rooms.probe_hosted_room(coord.path, room_id="room")


def test_member_capability_cannot_authorize_another_room_or_turn(pg_profiles):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        coord = coordination(db)
        create(coord)
        create(coord, subject="bob", room_id="other")
        identity = driver.TaskIdentity("other", "task", "thread", "turn")
        driver.admit_task(coord.path, identity, payload={"target_profile": "ops", "prompt": "input", "source_event_seq": 1}, clock=lambda: 10)
        lease = driver.acquire_lease(coord.path, room_id="other", gateway_id="gateway", authority_epoch=1, process_generation="process", ttl_seconds=30, clock=lambda: 10)
        driver.start_task(coord.path, identity, lease, expected_cancel_generation=0, clock=lambda: 10)
        authorization = HostedMemberAuthorization(coord, available=lambda: True, owner="alice",
            binding=HostedRoomBinding("room", "gateway", 1), member="ops", profile="ops")
        assert not authorization("submit", identity, 1)
        assert not authorization("submit", driver.TaskIdentity("room", "task", "wrong", "turn"), 1)
