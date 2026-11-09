"""Named Core driver reads and fences, with no SQLite statement execution surface."""

from sqlalchemy import select, update
from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.tables.rooms import rooms
from hermes_db.tables.room_runs import leases, tasks


def active_room(conn, store, room_id):
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, room_id)).with_for_update()).mappings().one_or_none()
    if row is None or row["disbanded_at"] is not None:
        raise native.RoomUnavailableError("hosted room does not exist" if row is None else "hosted room is disbanded")
    return room_repo.decode(row)


def require_authority(conn, store, room_id, gateway, epoch):
    row = active_room(conn, store, room_id)
    if row["authority_gateway_id"] != gateway or row["authority_epoch"] != epoch:
        raise native.StaleLeaseError("hosted room authority changed")
    return row


def lease_row(conn, store, room_id):
    row = conn.execute(select(leases).where(room_repo.scope(leases, store, room_id)).with_for_update()).mappings().one_or_none()
    return dict(row) if row is not None else None


def active_lease(conn, store, lease, *, now):
    require_authority(conn, store, lease.room_id, lease.gateway_id, lease.authority_epoch)
    row = lease_row(conn, store, lease.room_id)
    if not native._lease_row_matches(row, lease) or row["released_at"] is not None or row["expires_at"] <= now:
        raise native.StaleLeaseError("driver lease is stale or expired")
    return row


def task_key(store, identity):
    return room_repo.scope(tasks, store, identity.room_id) & (tasks.c.task_id == identity.task_id)


def task(conn, store, identity, *, required=True, lock=True):
    statement = select(tasks).where(task_key(store, identity))
    row = conn.execute(statement.with_for_update() if lock else statement).mappings().one_or_none()
    if row is None:
        if required:
            raise native.TaskConflictError("task does not exist")
        return None
    row = room_repo.decode(row)
    if native._task_identity_from_row(row) != identity:
        raise native.TaskConflictError("task_id is already bound to a different turn")
    return row


def task_rows(conn, store, room_id, status=None):
    statement = select(tasks).where(room_repo.scope(tasks, store, room_id))
    if status is not None:
        statement = statement.where(tasks.c.status == status)
    return [room_repo.decode(row) for row in conn.execute(statement.order_by(
        tasks.c.source_event_seq, tasks.c.created_at, tasks.c.task_id)).mappings()]


def update_lease(conn, store, room_id, **fields):
    conn.execute(update(leases).where(room_repo.scope(leases, store, room_id)).values(**fields))


def update_task(conn, store, identity, **fields):
    conn.execute(update(tasks).where(task_key(store, identity)).values(**room_repo.values(tasks, fields)))
