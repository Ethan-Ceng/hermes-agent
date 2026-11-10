"""The real room authorization and FIFO admission share one PG transaction and receipt."""

import asyncio
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
import time
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def owner(pg_profiles, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import SessionAuthority
    from hermes_cli.db_sessions import open_session_store
    from hermes_db.integration.runtime_access import runtime_for_store
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as resource:
        db = resource.session_store
        monkeypatch.setattr(SessionStore, "_open_session_db_for_active_scope", lambda self, **kwargs: db)
        store = SessionStore(home / "sessions", GatewayConfig())
        store._db = db
        runner = SimpleNamespace(session_store=store, _session_db=db, adapters={}, _draining=False,
            config=GatewayConfig(), _adapter_for_source=lambda source: None)
        epoch = runtime_for_store(db).begin_epoch(instance_id="api-owner")
        authority = SessionAuthority(runner, profile_id=str(home), instance_id="api-owner", db=db, epoch=epoch)
        runner.session_authority = authority
        yield authority, db


@pytest.mark.asyncio
async def test_room_fence_and_admission_are_atomic_and_replay_lost_confirmation(owner, monkeypatch):
    from gateway import hosted_room_driver as tasks
    from gateway.hosted_rooms import create_room
    from gateway.session_hosted_service import CanonicalHostedRoomService
    from gateway.session_hosted_storage import HostedAdmissionFence
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.runtime.postgres.queries.runtime import set_meta
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_state_runtime import RuntimeStoreError
    from tui_gateway.hosted_room_driver import HostedRoomBinding
    authority, db = owner
    home = db.scope.profile_home
    monkeypatch.setattr("gateway.hosted_rooms.local_authority_gateway_id", lambda: "test")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda *args: {
        "model": {"provider": "custom", "default": "fixture", "base_url": "http://x.invalid/v1"}})
    monkeypatch.setattr(authority, "_schedule", lambda ref: None)
    service = CanonicalHostedRoomService(authority, asyncio.get_running_loop())
    monkeypatch.setattr(service, "profile_homes", lambda: {"default": home})
    service.authorize_room("alice", "room", create=True)
    create_room(service.db_path, room_id="room", name="Room", authority_gateway_id="test",
        members=[{"member_id": "one", "profile": "default", "handle": "bot"}])
    identity = tasks.TaskIdentity("room", "task", "thread", "turn")
    tasks.admit_task(service.db_path, identity, payload={"target_profile": "default", "target_member_id": "one",
        "source_event_seq": 1, "prompt": "frozen"}, clock=time.time)
    lease = tasks.acquire_lease(service.db_path, room_id="room", gateway_id="test", authority_epoch=1,
        process_generation="owner", ttl_seconds=30, clock=time.time)
    tasks.start_task(service.db_path, identity, lease, expected_cancel_generation=0, clock=time.time)
    task, = tasks.list_tasks(service.db_path, room_id="room")
    rpc = service._resolve_member_transport(HostedRoomBinding("room", "test", 1), task)
    created = await rpc._create({})
    assert db.get_session(created["session_id"])["source"] == "bot_room"
    assert db.get_session(created["session_id"])["hidden"]
    args = {"task": identity, "execution_generation": task["execution_generation"], "prompt": "frozen",
        "on_terminal": lambda receipt: None}
    with db._transactions.write() as conn:
        set_meta(conn, db.scope, "gateway.hosted.owner.v1:room", "bob")
    with pytest.raises(RuntimeStoreError, match="permission_denied"):
        await rpc._submit(args)
    assert runtime_for_store(db).list_admissions(session_id=rpc.ref.session_id) == []
    with db._transactions.write() as conn:
        set_meta(conn, db.scope, "gateway.hosted.owner.v1:room", "alice")
    original, apply = db._context.write, HostedAdmissionFence.apply
    writer, authorized = [], []

    @contextmanager
    def confirmation_lost():
        with original() as connection:
            writer.append(connection)
            yield connection
        raise UnknownCommitError("lost confirmation after real admission COMMIT")

    def same_connection(fence, connection, scope):
        assert connection is writer[-1]
        authorized.append(True)
        return apply(fence, connection, scope)

    with monkeypatch.context() as patch:
        patch.setattr(db._context, 'write', confirmation_lost)
        patch.setattr(HostedAdmissionFence, "apply", same_connection)
        with pytest.raises(UnknownCommitError):
            await rpc._submit(args)
    assert authorized and db._transactions.engine.pool.checkedout() == 0
    accepted = await rpc._submit(args)
    rows = runtime_for_store(db).list_admissions(session_id=rpc.ref.session_id)
    assert len(rows) == 1 and rows[0]["admission_id"] == accepted["admission_id"]
    assert service.check_admission(rpc.ref, rows[0])["identity"] == identity
    assert rows[0]["request_id"] == "hosted:" + json.dumps([asdict(identity), task["execution_generation"]],
        sort_keys=True, separators=(",", ":"))
