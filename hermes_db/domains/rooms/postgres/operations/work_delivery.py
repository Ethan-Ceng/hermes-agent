"""Freeze an immutable source tip until its exact passive ACK arrives."""

import json

from sqlalchemy import update
from gateway import hosted_room_work_records as native
from hermes_db.domains.rooms.postgres.operations.work import capture_locked
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, work as repo
from hermes_db.tables.room_work import pending


def prepare_locked(conn, store, *, room_id, target_install_id, route_generation, local_gateway_id, through_seq):
    room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
    if room["authority_gateway_id"] != local_gateway_id:
        raise native.WorkRecordError("work record source is unavailable")
    scope = dict(room_id=room_id, authority=dict(gateway_id=room["authority_gateway_id"], epoch=room["authority_epoch"]))
    key = repo.record_key(pending, store, scope, target_install_id)
    old = repo.read(conn, store, pending, key)
    previous = repo.validate_locked(conn, store, pending, old) if old is not None else None
    if old is not None and old["disposition"] != "current":
        raise native.WorkRecordError("pending work record is not current")
    if old is not None and old["status"] != "acked":
        if old["route_generation"] == route_generation and old["status"] in native.BLOCKED_DELIVERY_STATUSES:
            return None
        record = previous
        if (record["home_install_id"] != local_gateway_id or record["authority"] != scope["authority"]
                or record["roster_sha256"] != native.roster_digest(json.loads(room["members_json"]))):
            raise native.WorkRecordError("pending work record source changed")
        conn.execute(update(pending).where(key, pending.c.disposition == "current").values(route_generation=route_generation, status="pending"))
    else:
        record = capture_locked(conn, store, room_id=room_id, local_gateway_id=local_gateway_id)
        if old is not None and (old["revision"], old["digest"]) == (record["revision"], record["digest"]):
            return None
        repo.save(conn, store, pending, record, target_install_id=target_install_id, route_generation=route_generation)
    return record if record["history"]["seq"] <= through_seq else None


def status_locked(conn, store, *, room_id, target_install_id, route_generation, record, status):
    key = repo.record_key(pending, store, record, target_install_id)
    row = repo.read(conn, store, pending, key)
    if row is None or row["room_id"] != room_id or row["disposition"] != "current":
        return False
    try:
        if repo.validate_locked(conn, store, pending, row) != record:
            return False
    except native.InvalidStoredWorkRecord:
        return False
    return conn.execute(update(pending).where(key, pending.c.route_generation == route_generation,
        pending.c.revision == record["revision"], pending.c.digest == record["digest"], pending.c.disposition == "current").values(status=status)).rowcount == 1


def _write(store, operation, **params):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        try:
            return operation(conn, store, **params)
        except native.InvalidStoredWorkRecord:
            pass
    raise native.InvalidStoredWorkRecord("stored work evidence is invalid")


def prepare_delivery(store, **params):
    return _write(store, prepare_locked, **params)


def delivery_status(store, **params):
    return _write(store, status_locked, **params)


def acknowledge(store, *, ack, record, **params):
    if native.encode(ack) != native.encode(native.acknowledgement(record)):
        return False
    return delivery_status(store, record=record, status="acked", **params)
