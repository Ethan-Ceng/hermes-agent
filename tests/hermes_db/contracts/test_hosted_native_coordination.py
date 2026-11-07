"""Independent room coordination cannot fall back to SQLite canonical sessions."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest


def test_room_coordination_isolates_database_targets_and_schemas_but_not_credentials(tmp_path):
    from sqlalchemy.engine import make_url
    from gateway.session_hosted_storage import coordination_path
    from hermes_db.scope import DatabaseScope
    def store(dsn, schema='rooms'):
        return SimpleNamespace(scope=DatabaseScope(tmp_path, 'same-store'),
            _transactions=SimpleNamespace(engine=SimpleNamespace(url=make_url(dsn)), schema=schema))
    first = coordination_path(store('postgresql+psycopg://one:secret@host/first'))
    assert first == coordination_path(store('postgresql+psycopg://two:rotated@host/first'))
    assert first != coordination_path(store('postgresql+psycopg://one:secret@host/second'))
    assert first != coordination_path(store('postgresql+psycopg://one:secret@host/first', 'other'))


@pytest.mark.asyncio
async def test_native_hosted_room_ownership_uses_scoped_local_coordination_only(core_pair, monkeypatch):
    from gateway.hosted_rooms import create_room
    from gateway.session_hosted_service import CanonicalHostedRoomService
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.runtime_store import PostgresRuntimeStore
    from hermes_state_runtime import RuntimeStoreError
    db, _other = core_pair
    home = db.scope.profile_home
    home.mkdir(parents=True, exist_ok=True)
    token = set_hermes_home_override(home)
    epoch = PostgresRuntimeStore(db).begin_epoch(instance_id="owner")
    owner = SimpleNamespace(db=db, profile_id=str(home), epoch=epoch)
    monkeypatch.setattr("gateway.hosted_rooms.local_authority_gateway_id", lambda: "test")
    try:
        service = CanonicalHostedRoomService(owner, asyncio.get_running_loop())
        assert service.db_path.parent == home and service.db_path.name != "state.db"
        service.authorize_room("alice", "room", create=True)
        create_room(service.db_path, room_id="room", name="Room", authority_gateway_id="test",
            members=[{"member_id": "default", "profile": "default", "handle": "bot"}])
        restarted = CanonicalHostedRoomService(owner, asyncio.get_running_loop())
        assert restarted.db_path == service.db_path
        assert restarted.authorize_room("alice", "room")
        assert [binding.room_id for binding in restarted.bindings()] == ["room"]
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            restarted.authorize_room("bob", "room", create=True)
        with sqlite3.connect(service.db_path) as conn:
            names = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names & {"sessions", "messages", "session_admissions"}
        assert not (home / "state.db").exists()
        epoch = PostgresRuntimeStore(db).begin_epoch(instance_id="replacement")
        replacement = SimpleNamespace(db=db, profile_id=str(home), epoch=epoch)
        assert CanonicalHostedRoomService(replacement, asyncio.get_running_loop()).db_path == service.db_path
        with pytest.raises(RuntimeStoreError, match="stale_epoch"):
            service.authorize_room("alice", "room")
    finally:
        reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_native_hosted_submit_holds_room_fence_before_pg_and_replays_lost_confirmation(api_owner, monkeypatch):
    from contextlib import contextmanager
    from dataclasses import asdict
    import json
    import time
    from gateway import hosted_room_driver as tasks
    from gateway.hosted_rooms import create_room
    from gateway.session_hosted_service import CanonicalHostedRoomService
    from hermes_db.errors import UnknownCommitError
    from hermes_db.runtime_access import runtime_for_store
    from hermes_state_runtime import RuntimeStoreError
    from tui_gateway.hosted_room_driver import HostedRoomBinding
    owner, db, _other = api_owner
    home = db.scope.profile_home
    monkeypatch.setattr("gateway.hosted_rooms.local_authority_gateway_id", lambda: "test")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda *args: {
        "model": {"provider": "custom", "default": "fixture", "base_url": "http://x.invalid/v1"}})
    monkeypatch.setattr(owner, "_schedule", lambda ref: None)
    service = CanonicalHostedRoomService(owner, asyncio.get_running_loop())
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
    service._coordination.write(lambda conn: conn.execute("UPDATE state_meta SET value='bob' WHERE key=?",
        ("gateway.hosted.owner.v1:room",)))
    with pytest.raises(RuntimeStoreError, match="permission_denied"):
        await rpc._submit(args)
    assert runtime_for_store(db).list_admissions(session_id=rpc.ref.session_id) == []
    service._coordination.write(lambda conn: conn.execute("UPDATE state_meta SET value='alice' WHERE key=?",
        ("gateway.hosted.owner.v1:room",)))
    original = db._write

    @contextmanager
    def confirmation_lost():
        # The local fence must precede acquiring the canonical writer.
        with sqlite3.connect(service.db_path, timeout=0) as probe:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                probe.execute("BEGIN IMMEDIATE")
        with original() as conn:
            yield conn
        raise UnknownCommitError("lost confirmation")

    with monkeypatch.context() as patch:
        patch.setattr(db, "_write", confirmation_lost)
        with pytest.raises(UnknownCommitError):
            await rpc._submit(args)
    # The local guard is released even when PG's outcome cannot be acknowledged.
    service._coordination.write(lambda conn: conn.execute("SELECT 1"))
    accepted = await rpc._submit(args)
    rows = runtime_for_store(db).list_admissions(session_id=rpc.ref.session_id)
    assert len(rows) == 1 and rows[0]["admission_id"] == accepted["admission_id"]
    assert service.check_admission(rpc.ref, rows[0])["identity"] == identity
    assert rows[0]["request_id"] == "hosted:" + json.dumps([asdict(identity), task["execution_generation"]],
        sort_keys=True, separators=(",", ":"))
    assert not (home / "state.db").exists()
