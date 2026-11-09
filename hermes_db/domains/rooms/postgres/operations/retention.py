"""Prune payloads under the store quota lock; retired room identities survive forever."""

from sqlalchemy import delete, select
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.rooms import rooms, links, reservations, remote_runs


def prune_locked(conn, store, *, now=None, max_gateway_event_bytes=None):
    from gateway import hosted_rooms as native
    statement = select(rooms.c.room_id, rooms.c.disbanded_at, rooms.c.event_bytes).where(repo.scope(rooms, store),
        rooms.c.disbanded_at.is_not(None)).order_by(rooms.c.disbanded_at.desc(), rooms.c.room_id)
    rows = list(conn.execute(statement).mappings())
    selected = {row["room_id"] for index, row in enumerate(rows) if index >= native.MAX_DISBANDED_ROOM_TOMBSTONES
                or (now is not None and row["disbanded_at"] <= now - native.DISBANDED_ROOM_RETENTION_SECONDS)}
    if max_gateway_event_bytes is not None:
        total = repo.gateway_bytes(conn, store)
        for row in reversed(rows):
            if total <= max_gateway_event_bytes:
                break
            selected.add(row["room_id"])
            total -= row["event_bytes"]
    for row in rows:
        if row["room_id"] in selected:
            repo.retire(conn, store, row["room_id"], row["disbanded_at"])
    if selected:
        for table in (links, reservations, remote_runs):
            keys = [repo.values(table, {"room_id": room_id})["room_id"] for room_id in selected]
            conn.execute(delete(table).where(repo.scope(table, store), table.c.room_id.in_(keys)))
        conn.execute(delete(rooms).where(repo.scope(rooms, store), rooms.c.room_id.in_(selected)))
    return len(selected)


def prune_disbanded_rooms(store, *, now=None):
    from gateway.hosted_rooms_common import clock
    with store.write() as conn:
        repo.lock_store(conn, store)
        return prune_locked(conn, store, now=clock(now))


def event_size(conn, store, room, event_id, kind, actor_json, payload_json, *, allow_control=False):
    from gateway import hosted_rooms as native
    from gateway.hosted_rooms_common import utf8_len
    size = utf8_len(event_id, kind, actor_json, payload_json)
    count_reserve = native.CONTROL_EVENT_COUNT_RESERVE if allow_control else 0
    byte_reserve = native.CONTROL_EVENT_BYTE_RESERVE if allow_control else 0
    if room["next_seq"] - 1 >= native.MAX_EVENTS_PER_ROOM + count_reserve:
        raise native.HostedRoomError("This Group Chat reached its history limit. Start a new Group Chat to continue.")
    if room["event_bytes"] + size > native.MAX_ROOM_EVENT_BYTES + byte_reserve:
        raise native.HostedRoomError("This Group Chat reached its storage limit. Start a new Group Chat to continue.")
    limit = native.MAX_GATEWAY_EVENT_BYTES + byte_reserve
    if repo.gateway_bytes(conn, store) + size > limit:
        prune_locked(conn, store, max_gateway_event_bytes=max(0, limit - size))
    if repo.gateway_bytes(conn, store) + size > limit:
        raise native.HostedRoomError("Group Chat storage is full on this host. Delete an old Group Chat and try again.")
    return size
