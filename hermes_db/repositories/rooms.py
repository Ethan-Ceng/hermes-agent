"""Scoped Core statements; room quota locks precede room and replica row locks."""

from sqlalchemy import LargeBinary, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.rooms import rooms, events, retired, room_locks
from hermes_db.core.values import encode_text, decode_text


def scope(table, store, room_id=None):
    condition = table.c.store_id == store.scope.require_store_id()
    return condition if room_id is None else and_(condition, table.c.room_id == values(table, {"room_id": room_id})["room_id"])


def key(table, store, fields):
    return and_(scope(table, store), *(table.c[name] == value for name, value in values(table, fields).items()))


def record(row):
    return {name: value for name, value in decode(row).items() if name != "store_id"}


def values(table, record):
    return {key: encode_text(value) if isinstance(table.c[key].type, LargeBinary) else value for key, value in record.items()}


def decode(row):
    return {key: decode_text(value) if isinstance(value, (bytes, memoryview)) else value for key, value in row.items()}


def insert_row(conn, store, table, record):
    if table is events:
        import json
        payload = json.loads(record["payload_json"])
        record = dict(record, **{key: payload.get(field) if isinstance(payload.get(field), str) else None
            for key, field in (("policy_thread_key", "thread_id"), ("policy_discussion_key", "discussion_event_id"))})
    conn.execute(table.insert().values(store_id=store.scope.require_store_id(), **values(table, record)))


def lock_store(conn, store):
    conn.execute(insert(room_locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(room_locks.c.store_id).where(scope(room_locks, store)).with_for_update()).one()


def room(conn, store, room_id, *, include_disbanded=False, lock=False):
    from gateway.hosted_rooms import RoomHistoryExpiredError, RoomNotFoundError
    statement = select(rooms).where(scope(rooms, store, room_id))
    row = conn.execute(statement.with_for_update() if lock else statement).mappings().one_or_none()
    if row is not None and (include_disbanded or row["disbanded_at"] is None):
        return decode(row)
    if row is None and conn.scalar(select(retired.c.room_id).where(scope(retired, store, room_id))) is not None:
        raise RoomHistoryExpiredError("Group Chat history expired; room_id remains permanently retired")
    raise RoomNotFoundError("hosted room not found")


def event(conn, store, room_id, event_id):
    row = conn.execute(select(events).where(scope(events, store, room_id), events.c.event_id == encode_text(event_id))).mappings().one_or_none()
    return decode(row) if row is not None else None


def change_room(conn, store, room_id, **fields):
    conn.execute(update(rooms).where(scope(rooms, store, room_id)).values(**values(rooms, fields)))


def gateway_bytes(conn, store):
    return int(conn.scalar(select(func.coalesce(func.sum(rooms.c.event_bytes), 0)).where(scope(rooms, store))))


def retire(conn, store, room_id, timestamp):
    conn.execute(insert(retired).values(store_id=store.scope.require_store_id(), room_id=room_id,
                                       retired_at=timestamp).on_conflict_do_nothing())
