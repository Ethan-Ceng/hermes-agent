"""Room commit uncertainty, transactional callbacks, capacity and a real process reopen."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys

import pytest

from gateway import hosted_rooms as rooms
from tests.hermes_db.postgresql.test_rooms_store import create, append

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_real_commit_lost_ack_is_replayed_once(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.backends.postgresql.transactions import Transactions
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        original = Transactions.write
        armed = [True]
        @contextmanager
        def lose_ack(self, *args, **kwargs):
            with original(self, *args, **kwargs) as conn:
                yield conn
            if armed[0]:
                armed[0] = False
                raise UnknownCommitError("injected room commit confirmation loss")
        with monkeypatch.context() as patch:
            patch.setattr(Transactions, "write", lose_ack)
            with pytest.raises(UnknownCommitError):
                append(location, "once")
        assert append(location, "once")["idempotent"]
        assert rooms.read_events(location, room_id="room")["latest_seq"] == 1


def test_quota_reserves_control_events_and_failed_create_rolls_back_admission(pg_profiles, monkeypatch):
    from sqlalchemy import select
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
    from hermes_db.tables.conversations import system_prompts
    with pg_profiles("one"):
        location = rooms.default_db_path()
        def admit(conn, scope):
            conn.execute(system_prompts.insert().values(store_id=scope.require_store_id(), hash="admit-proof", prompt=b"admitted"))
        with monkeypatch.context() as patch:
            patch.setattr(rooms, "MAX_ACTIVE_ROOMS", 0)
            with pytest.raises(rooms.HostedRoomError, match="too many active"):
                rooms.create_room(location, room_id="rejected", name="rejected", members=[], authority_gateway_id="gateway-a",
                                  admit=CoreEffect(admit))
        with acquire_profile_domain("rooms") as store, store.read() as conn:
            assert conn.scalar(select(system_prompts.c.hash).where(system_prompts.c.store_id == "one",
                system_prompts.c.hash == "admit-proof")) is None
        assert not rooms.probe_hosted_room(location, room_id="rejected")
        create(location)
        monkeypatch.setattr(rooms, "MAX_EVENTS_PER_ROOM", 1)
        append(location, "first")
        with pytest.raises(rooms.HostedRoomError, match="history limit"):
            append(location, "too-many")
        stopped = rooms.request_room_stop(location, room_id="room", cancel_id="stop", expected_gateway_id="gateway-a", expected_epoch=1)
        assert stopped["seq"] == 2
        assert rooms.read_events(location, room_id="room")["latest_seq"] == 2


def test_real_new_process_reads_and_appends_without_any_sqlite(pg_profiles):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        location = rooms.default_db_path()
        create(location)
        append(location, "before-restart")
        code = r'''
import sqlite3, sys
def reject(*args, **kwargs):
    raise AssertionError("SQLite connection rejected in PG room restart process")
sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == 'sqlite3.connect' else None)
from gateway import hosted_rooms as rooms
location = rooms.default_db_path()
page = rooms.read_events(location, room_id="room")
assert page["latest_seq"] == 1 and page["events"][0]["payload"]["zero"] == 0
rooms.append_event(location, room_id="room", event_id="after-restart", kind="message.user",
    actor={"kind":"user","id":"owner"}, payload={"text":"persisted\u0000🙂"},
    authority_gateway_id="gateway-a", authority_epoch=1)
print("PG_ROOM_RESTART_OK")
'''
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3], env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_ROOM_RESTART_OK" in result.stdout
        assert rooms.read_events(location, room_id="room")["latest_seq"] == 2


def test_demotion_fences_stale_authority_even_when_history_capacity_is_exhausted(pg_profiles, monkeypatch):
    from gateway import hosted_room_replicas as replicas
    with pg_profiles("one"):
        location = rooms.default_db_path()
        local = rooms.local_authority_gateway_id()
        rooms.create_room(location, room_id="room", name="full", members=[], authority_gateway_id=local)
        monkeypatch.setattr(rooms, "MAX_EVENTS_PER_ROOM", 0)
        monkeypatch.setattr(rooms, "CONTROL_EVENT_COUNT_RESERVE", 0)
        monkeypatch.setattr(rooms, "MAX_GATEWAY_EVENT_BYTES", 0)
        result = replicas.demote_room(location, room_id="room", observed_gateway_id="new-owner", observed_epoch=2)
        assert result["authority_epoch"] == 2
        assert rooms.room_state(location, room_id="room")["authority_gateway_id"] == "new-owner"
        with pytest.raises(rooms.AuthorityConflictError):
            rooms.append_event(location, room_id="room", event_id="stale", kind="message.user", actor={"kind": "user", "id": "u"},
                payload={}, authority_gateway_id=local, authority_epoch=1)


def test_captured_room_reference_rejects_profile_storage_identity_change(pg_profiles):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_db.errors import StorageConfigurationError
    with pg_profiles("one") as home:
        location = rooms.default_db_path()
        create(location)
        config = read_user_config_raw(home / "config.yaml")
        config["storage"]["postgresql"]["store_id"] = "changed"
        atomic_config_write(home / "config.yaml", config)
        with pytest.raises(StorageConfigurationError, match="store_id changed"):
            rooms.list_rooms(location)


def test_replica_competing_ingest_and_gap_failure_leave_checkpoint_intact(pg_profiles):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from gateway import hosted_room_replicas as replicas
    with pg_profiles("one"):
        source = rooms.default_db_path()
        create(source)
        append(source, "first")
        append(source, "second")
        page = rooms.read_events(source, room_id="room")
    with pg_profiles("two"):
        target = rooms.default_db_path()
        def ingest():
            return replicas.ingest_page(target, room_id="room", room_name="copy", members=[], page=page)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, ingest) for _ in range(2)]
            assert sorted(future.result()["ingested"] for future in futures) == [0, 2]
        from copy import deepcopy
        gap = deepcopy(page)
        gap["events"] = [dict(page["events"][0], seq=4, event_id="gap")]
        with pytest.raises(replicas.ReplicaGapError):
            replicas.ingest_page(target, room_id="room", room_name="copy", members=[], page=gap)
        assert replicas.replica_state(target, room_id="room")["last_seq"] == 2


def test_disband_retention_purges_metadata_but_keeps_permanent_identity(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        record = dict(room_id="room", member_id="member", target_url="https://example.test", target_profile="ops",
            grant="fixture-grant", catalog_json="{}", cancellation_scope_id="scope", trace_id="trace",
            transport_security="https", status="ready", updated_at=1)
        rooms.upsert_room_link_record(location, record=record, max_links=1)
        claims = dict(room_id="room", member_id="member", target_profile="ops", authority_gateway_id="gateway-a", authority_epoch=1)
        rooms.reserve_peer_room(location, claims=claims, expires_at=100, now=1)
        rooms.disband_room(location, room_id="room", expected_gateway_id="gateway-a", expected_epoch=1, now=2)
        assert rooms.prune_disbanded_rooms(location, now=rooms.DISBANDED_ROOM_RETENTION_SECONDS + 3) == 1
        assert rooms.list_room_link_records(location) == []
        assert not rooms.peer_room_is_reserved(location, room_id="room", target_profile="ops", now=4)
        with pytest.raises(rooms.RoomConflictError):
            create(location)
