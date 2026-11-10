"""Actual task transitions, remote receipts and invalid passive evidence on PG."""
import hermes_db.domains.rooms.work_rules as _storage_patch_1

import json

import pytest
from sqlalchemy import select, update

from gateway import hosted_room_driver as driver, hosted_room_work_records as work, hosted_rooms as rooms
from hermes_cli.db_domains import acquire_profile_domain
from hermes_db.tables.room_work import source, publications, pending
from hermes_db.core.values import encode_text, decode_text

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def prepare(location, *, peer=False):
    members = [{"profile": "ops", "handle": "ops"}]
    if peer:
        members[0]["target"] = {"kind": "peer", "installation_id": "peer", "profile": "ops"}
    rooms.create_room(location, room_id="room", name="Room", members=members, authority_gateway_id="owner", now=10)
    rooms.append_event(location, room_id="room", event_id="input", kind="message.user", actor={"kind": "user", "id": "alice"},
        payload={"text": "hello"}, authority_gateway_id="owner", authority_epoch=1, now=10)
    identity = driver.TaskIdentity("room", "task", "thread", "turn")
    driver.admit_task(location, identity, payload={"target_profile": "ops", "prompt": "private input", "source_event_seq": 1}, clock=lambda: 10)
    return identity


def snapshot():
    with acquire_profile_domain("rooms") as store, store.read() as conn:
        raw = conn.scalar(select(source.c.record_json).where(source.c.store_id == store.scope.store_id, source.c.disposition == "current"))
    assert raw is not None
    return work.validate(json.loads(decode_text(raw)))


def lease(location, process="process-a", now=10):
    return driver.acquire_lease(location, room_id="room", gateway_id="owner", authority_epoch=1,
        process_generation=process, ttl_seconds=10, clock=lambda: now)


def test_real_transitions_capture_atomic_private_snapshot_and_unknown_recovery(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        queued = snapshot()
        assert queued["availability"] == "available" and queued["tasks"][0]["phase"] == "queued"
        assert "private input" not in work.encode(queued)
        assert work.capture(location, room_id="room", local_gateway_id="owner") == queued
        attempt = driver.start_task(location, identity, lease(location), expected_cancel_generation=0, clock=lambda: 10)
        running = snapshot()
        assert running["revision"] == queued["revision"] + 1 and running["tasks"][0]["phase"] == "running"
        successor = lease(location, "process-b", 21)
        driver.recover_room(location, successor, clock=lambda: 21)
        unknown = snapshot()
        assert unknown["tasks"][0]["phase"] == "indeterminate"
        with pytest.raises(driver.StaleLeaseError):
            driver.settle_task(location, attempt, settlement_id="late", status="settled", result={}, clock=lambda: 21)
        assert snapshot() == unknown
        driver.begin_task_cancel(location, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 21)
        assert snapshot()["tasks"][0]["phase"] == "stopping"
        driver.complete_task_cancel(location, identity, cancel_id="stop", expected_cancel_generation=1, clock=lambda: 21)
        assert snapshot()["tasks"][0]["phase"] == "cancelled"


def test_broken_evidence_retains_bytes_and_does_not_block_stop(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        with acquire_profile_domain("rooms") as store, store.write() as conn:
            conn.execute(update(source).where(source.c.store_id == "one").values(record_json=encode_text("broken")))
        driver.cancel_task(location, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 10)
        assert driver.get_task(location, identity)["status"] == "cancelled"
        with acquire_profile_domain("rooms") as store, store.read() as conn:
            row = conn.execute(select(source.c.disposition, source.c.record_json).where(source.c.store_id == "one")).one()
        assert (row.disposition, decode_text(row.record_json)) == ("invalid", "broken")
        with pytest.raises(work.InvalidStoredWorkRecord):
            work.capture(location, room_id="room", local_gateway_id="owner")


def test_evidence_capacity_never_rolls_back_primary_task_transition(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        before = snapshot()
        monkeypatch.setattr(_storage_patch_1, "MAX_STORE_BYTES", 1)
        driver.cancel_task(location, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 10)
        assert driver.get_task(location, identity)["status"] == "cancelled"
        assert snapshot() == before


def test_real_remote_receipt_captures_without_next_driver_transition(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        prepare(location, peer=True)
        record = dict(room_id="room", home_install_id="owner", authority_gateway_id="owner", authority_epoch=1,
            member_id="ops", target_install_id="peer", target_profile="ops", task_id="task", execution_generation=1,
            run_id="run", session_id="session")
        rooms.upsert_remote_run_receipt(location, record=record)
        first = snapshot()
        assert first["receipts"] == [record]
        rooms.upsert_remote_run_receipt(location, record=record)
        assert snapshot() == first


def test_published_terminals_only_are_pruned_and_snapshot_filters_them(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        identity = prepare(location)
        driver.cancel_task(location, identity, cancel_id="stop", expected_cancel_generation=0, clock=lambda: 10)
        assert driver.prune_published_terminal_tasks(location, room_id="room", clock=lambda: 10**8) == 0
        with acquire_profile_domain("rooms") as store, store.write() as conn:
            conn.execute(publications.insert().values(store_id="one", room_id="room", task_id=encode_text("task"), kind="turn.cancelled", execution_generation=0, seq=1))
        evidence = work.capture(location, room_id="room", local_gateway_id="owner")
        assert evidence["tasks"] == []
        assert driver.prune_published_terminal_tasks(location, room_id="room", clock=lambda: 10**8) == 1
        assert driver.list_tasks(location, room_id="room") == []


def test_pending_exact_ack_and_successor_lineage_keep_old_bytes_frozen(pg_profiles):
    from hermes_db.errors import StorageConflictError
    with pg_profiles("one"):
        location = rooms.default_db_path()
        prepare(location)
        params = dict(room_id="room", target_install_id="peer", route_generation="route-1", local_gateway_id="owner", through_seq=0)
        assert work.prepare_delivery(location, **params) is None
        # The frozen prefix stays at seq1 while the real room tip advances.
        rooms.append_event(location, room_id="room", event_id="second", kind="message.user", actor={"kind": "user", "id": "alice"},
            payload={"text": "next"}, authority_gateway_id="owner", authority_epoch=1, now=11)
        record = work.prepare_delivery(location, **(params | {"through_seq": 10}))
        assert record["history"]["seq"] == 1
        acknowledgement = dict(room_id="room", target_install_id="peer", route_generation="route-1", record=record)
        assert not work.acknowledge(location, **acknowledgement, ack=work.acknowledgement(record) | {"revision": 999})
        assert not work.acknowledge(location, **(acknowledgement | {"route_generation": "wrong"}), ack=work.acknowledgement(record))
        with acquire_profile_domain("rooms") as store, store.read() as conn:
            original = conn.scalar(select(pending.c.record_json).where(pending.c.store_id == "one"))
        rooms.claim_authority(location, room_id="room", expected_gateway_id="owner", expected_epoch=1, new_gateway_id="successor", event_id="claim", now=12)
        assert not work.acknowledge(location, **acknowledgement, ack=work.acknowledgement(record))
        successor = work.capture(location, room_id="room", local_gateway_id="successor")
        assert successor["version"] == 2 and successor["incompleteness"] == ["prior_authority_work_unknown"]
        with acquire_profile_domain("rooms") as store, store.read() as conn:
            old = conn.execute(select(pending).where(pending.c.store_id == "one", pending.c.producer_epoch == 1)).mappings().one()
        assert old["disposition"] == "superseded_authority" and old["record_json"] == original
        with pytest.raises(StorageConflictError):
            with acquire_profile_domain("rooms") as store, store.write() as conn:
                conn.execute(update(pending).where(pending.c.store_id == "one", pending.c.producer_epoch == 1).values(status="acked"))
        current = work.prepare_delivery(location, **(params | {"local_gateway_id": "successor", "route_generation": "route-2", "through_seq": 10}))
        assert work.acknowledge(location, **(acknowledgement | {"route_generation": "route-2", "record": current}), ack=work.acknowledgement(current))
