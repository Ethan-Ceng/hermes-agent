"""Monotonic lease generations and exact owner/process/expiry fences on PG."""

import dataclasses
from sqlalchemy import select
from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, runs as repo
from hermes_db.tables.room_runs import leases, tasks


def acquire_lease(store, *, room_id, gateway_id, authority_epoch, process_generation, ttl_seconds, clock):
    room_id = native._identifier(room_id, label="room_id")
    gateway = native._identifier(gateway_id, label="gateway_id")
    epoch = native._bounded_int(authority_epoch, message="authority_epoch must be a positive integer", low=1)
    process = native._identifier(process_generation, label="process_generation")
    now, expiry = native._lease_window(ttl_seconds, clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.require_authority(conn, store, room_id, gateway, epoch)
        row = repo.lease_row(conn, store, room_id)
        if row is None:
            row = dict(room_id=room_id, gateway_id=gateway, authority_epoch=epoch, process_generation=process,
                       lease_generation=1, expires_at=expiry, acquired_at=now, updated_at=now, released_at=None)
            room_repo.insert_row(conn, store, leases, row)
            return native._lease_from_row(row)
        same = row["gateway_id"] == gateway and row["authority_epoch"] == epoch
        live = row["released_at"] is None and row["expires_at"] > now
        if same and row["process_generation"] == process and live:
            expiry = max(row["expires_at"], expiry)
            repo.update_lease(conn, store, room_id, expires_at=expiry, updated_at=now)
            return native._lease_from_row(dict(row, expires_at=expiry))
        if same and live:
            raise native.LeaseHeldError("room driver lease is held by another generation")
        fields = dict(gateway_id=gateway, authority_epoch=epoch, process_generation=process,
            lease_generation=row["lease_generation"] + 1, expires_at=expiry, acquired_at=now, updated_at=now, released_at=None)
        repo.update_lease(conn, store, room_id, **fields)
        return native._lease_from_row(dict(row, **fields), reclaimed=True)


def renew_lease(store, lease, *, ttl_seconds, clock):
    now, expiry = native._lease_window(ttl_seconds, clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        current = repo.active_lease(conn, store, lease, now=now)
        expiry = max(current["expires_at"], expiry)
        repo.update_lease(conn, store, lease.room_id, expires_at=expiry, updated_at=now)
    return dataclasses.replace(lease, expires_at=expiry, reclaimed=False)


def release_lease(store, lease, *, clock):
    now = native._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.require_authority(conn, store, lease.room_id, lease.gateway_id, lease.authority_epoch)
        row = repo.lease_row(conn, store, lease.room_id)
        if not native._lease_row_matches(row, lease):
            raise native.StaleLeaseError("driver lease is stale")
        if row["released_at"] is not None:
            return {"lease": native._lease_from_row(row), "idempotent": True}
        if row["expires_at"] <= now:
            raise native.StaleLeaseError("driver lease expired before release")
        if conn.scalar(select(tasks.c.task_id).where(room_repo.scope(tasks, store, lease.room_id), tasks.c.status == "running").limit(1)) is not None:
            raise native.InvalidTaskTransitionError("cannot release a room lease while tasks are running")
        repo.update_lease(conn, store, lease.room_id, expires_at=now, updated_at=now, released_at=now)
    return {"lease": native._lease_from_row(dict(row, expires_at=now, updated_at=now, released_at=now)), "idempotent": False}
