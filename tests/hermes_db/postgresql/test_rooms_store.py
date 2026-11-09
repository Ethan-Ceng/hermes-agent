"""Selected PG rooms: real events, idempotency, authority epochs and store isolation."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import pytest

from gateway import hosted_rooms as rooms

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]
USER = {"kind": "user", "id": "owner", "display_name": "用户🙂"}


def create(location, room_id="room"):
    return rooms.create_room(location, room_id=room_id, name="房间🙂\x00", members=[{"id": "ops", "zero": 0, "false": False}],
                             authority_gateway_id="gateway-a", now=1.5)


def append(location, event_id, **fields):
    return rooms.append_event(location, room_id="room", event_id=event_id, kind="message.user", actor=USER,
        payload={"text": "exact\x00🙂", "false": False, "zero": 0}, authority_gateway_id="gateway-a", authority_epoch=1, **fields)


def test_events_persist_exact_values_and_scope_without_sqlite(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        assert create(location)["name"] == "房间🙂\x00"
        first = append(location, "once", now=2.5)
        assert first["seq"] == 1
        assert append(location, "once", now=3)["idempotent"]
        with pytest.raises(rooms.EventConflictError):
            rooms.append_event(location, room_id="room", event_id="once", kind="message.user", actor=USER,
                payload={"changed": True}, authority_gateway_id="gateway-a", authority_epoch=1)
    with pg_profiles("two"):
        other = rooms.default_db_path()
        assert rooms.list_rooms(other) == []
        create(other)
        assert rooms.read_events(other, room_id="room")["events"] == []
        assert rooms.read_events(location, room_id="room")["events"][0]["payload"] == {"text": "exact\x00🙂", "false": False, "zero": 0}
    with pg_profiles("one"):
        assert rooms.room_state(rooms.default_db_path(), room_id="room")["latest_seq"] == 1
        assert rooms.list_rooms(location)[0]["members"][0]["false"] is False


def test_competing_writers_sequence_and_transfer_retire_fences(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result() for future in [pool.submit(copy_context().run, append, location, f"event-{i}") for i in range(2)]]
        assert sorted(row["seq"] for row in results) == [1, 2]
        claim = rooms.claim_authority(location, room_id="room", expected_gateway_id="gateway-a", expected_epoch=1,
                                      new_gateway_id="gateway-b", event_id="takeover")
        assert claim["authority_epoch"] == 2 and claim["claim_event"]["seq"] == 3
        with pytest.raises(rooms.AuthorityConflictError):
            append(location, "stale")
        rooms.disband_room(location, room_id="room", expected_gateway_id="gateway-b", expected_epoch=2, now=10)
        assert rooms.prune_disbanded_rooms(location, now=rooms.DISBANDED_ROOM_RETENTION_SECONDS + 11) == 1
        with pytest.raises(rooms.RoomHistoryExpiredError):
            rooms.read_events(location, room_id="room", include_disbanded=True)
        with pytest.raises(rooms.RoomConflictError):
            create(location)
        assert rooms.disband_room(location, room_id="room", expected_gateway_id="gateway-b", expected_epoch=2)["history_expired"]


def test_replica_ingest_takeover_demotion_and_reopen_keep_lineage(pg_profiles):
    from gateway import hosted_room_replicas as replicas
    with pg_profiles("one"):
        source = rooms.default_db_path()
        create(source)
        append(source, "first")
        page = rooms.read_events(source, room_id="room")
    with pg_profiles("two"):
        target = rooms.default_db_path()
        first = replicas.ingest_page(target, room_id="room", room_name="replica", members=[], page=page)
        assert first["stored_seq"] == 1 and first["ingested"] == 1
        assert replicas.ingest_page(target, room_id="room", room_name="replica", members=[], page=page)["ingested"] == 0
        assert replicas.replica_state(target, room_id="room")["authority"] == {"gateway_id": "gateway-a", "epoch": 1}
        promoted = replicas.promote_replica(target, room_id="room")
        assert promoted["authority_epoch"] == 2 and promoted["claim_seq"] == 2
        local = promoted["authority_gateway_id"]
        assert rooms.read_events(target, room_id="room")["events"][0]["payload"] == page["events"][0]["payload"]
        demoted = replicas.demote_room(target, room_id="room", observed_gateway_id="gateway-new", observed_epoch=3)
        assert demoted["authority_epoch"] == 3
        with pytest.raises(rooms.AuthorityConflictError):
            rooms.append_event(target, room_id="room", event_id="stale", kind="message.user", actor=USER, payload={},
                               authority_gateway_id=local, authority_epoch=2)
    with pg_profiles("two"):
        page = rooms.read_events(rooms.default_db_path(), room_id="room")
        assert page["latest_seq"] == 3
        assert [event["kind"] for event in page["events"]] == ["message.user", "authority.claimed", "authority.lost"]


def test_links_grants_reservations_and_remote_receipts_follow_store(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        record = dict(room_id="room", member_id="member", target_url="https://example.test", target_profile="ops",
            grant="fixture-grant", catalog_json='{"zero":0,"false":false,"text":"中文\\u0000"}', cancellation_scope_id="scope",
            trace_id="trace", transport_security="https", status="ready", updated_at=1.5)
        rooms.upsert_room_link_record(location, record=record, max_links=1)
        assert rooms.list_room_link_records(location) == [record]
        assert rooms.update_room_link_status(location, room_id="room", member_id="member", status="unavailable", now=2)
        claims = dict(room_id="room", member_id="member", target_profile="ops", authority_gateway_id="gateway-a",
                      authority_epoch=1, home_install_id="home", target_install_id="target", issued_at=1)
        rooms.reserve_peer_room(location, claims=claims, expires_at=100, now=1)
        assert rooms.peer_room_grant_is_current(location, claims=claims, now=2)
        rooms.revoke_room_grant_scope(location, claims=claims, expires_at=100, now=3)
        assert rooms.room_grant_is_revoked(location, claims=claims, now=4)
        assert not rooms.peer_room_is_reserved(location, room_id="room", target_profile="ops", now=4)
        attempt = {key: value for key, value in claims.items() if key != "issued_at"}
        attempt.update(task_id="task", execution_generation=1, run_id="run\x00🙂", session_id="session\x00🙂")
        rooms.upsert_remote_run_receipt(location, record=attempt, now=5)
        rooms.upsert_remote_run_receipt(location, record=attempt, now=6)
        assert rooms.remote_run_receipt(location, record=attempt)["session_id"] == "session\x00🙂"
        with pytest.raises(rooms.HostedRoomError, match="conflicts"):
            rooms.upsert_remote_run_receipt(location, record=attempt | {"run_id": "other"})
    with pg_profiles("two"):
        other = rooms.default_db_path()
        assert rooms.list_room_link_records(other) == []
        assert not rooms.room_grant_is_revoked(other, claims=claims, now=4)
        assert rooms.list_remote_run_receipts(other) == []
        assert len(rooms.list_remote_run_receipts(location, session_id="session\x00🙂")) == 1


def test_legacy_import_does_not_probe_or_fence_old_sqlite_when_pg_selected(pg_profiles):
    from gateway import hosted_rooms_gateway_import as gateway_import, hosted_rooms_legacy_import as legacy
    with pg_profiles("one") as home:
        old = home / "shared-state.db"
        old.write_bytes(b"preserved standalone SQLite dataset")
        assert gateway_import.source_for(home / "state.db") is None
        assert legacy.source_path(old) is None
        assert gateway_import.import_standalone_rooms(home / "state.db") == 0
        assert old.read_bytes() == b"preserved standalone SQLite dataset"


def test_canonical_room_coordination_uses_canonical_pg_target(pg_profiles):
    from contextlib import closing
    from types import SimpleNamespace
    from gateway.session_hosted_storage import RoomCoordination
    from hermes_db.access import open_session_store
    from hermes_db.domains.rooms import RoomStoreRef
    from hermes_db.integration.runtime_access import runtime_for_store
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        epoch = runtime_for_store(db).begin_epoch(instance_id="owner")
        coordination = RoomCoordination(SimpleNamespace(db=db, epoch=epoch))
        assert isinstance(coordination.path, RoomStoreRef)
        create(coordination.path)
        assert rooms.room_state(coordination.path, room_id="room")["name"] == "房间🙂\x00"
        assert not list(home.glob("hosted-pg-*.db"))
