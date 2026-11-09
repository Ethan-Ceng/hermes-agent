"""Authoritative room identity changes and immutable event publication on Core."""

from sqlalchemy import func, select
from gateway import hosted_rooms as native
from gateway.hosted_rooms_common import clock
from hermes_db.domains.runtime.postgres.operations import effects
from hermes_db.operations.room_retention import event_size
from hermes_db.repositories import rooms as repo
from hermes_db.tables.rooms import rooms, events, retired


def create_room(store, *, room_id, name, members, authority_gateway_id, now=None, admit=None):
    room_id, name = native._room_id(room_id), native._validate_room_name(name)
    normalized, members_json = native._validate_members(members)
    gateway = native._actor_id(authority_gateway_id, "authority_gateway_id")
    timestamp = clock(now)
    with store.write() as conn:
        effects.invoke(admit, conn, store.scope)
        repo.lock_store(conn, store)
        if conn.scalar(select(retired.c.room_id).where(repo.scope(retired, store, room_id))) is not None:
            raise native.RoomConflictError("room_id belongs to a disbanded room")
        row = conn.execute(select(rooms).where(repo.scope(rooms, store, room_id)).with_for_update()).mappings().one_or_none()
        if row is not None:
            existing = repo.decode(row)
            if existing["disbanded_at"] is not None:
                raise native.RoomConflictError("room_id belongs to a disbanded room")
            if existing["name"] != name or existing["members_json"] != members_json:
                raise native.RoomConflictError("room_id already exists with different state")
            if existing["authority_gateway_id"] != gateway:
                raise native.RoomConflictError("room_id already belongs to a different authority")
            return native._room_from_row(existing, idempotent=True)
        count = conn.scalar(select(func.count()).select_from(rooms).where(repo.scope(rooms, store), rooms.c.disbanded_at.is_(None)))
        if count >= native.MAX_ACTIVE_ROOMS:
            raise native.HostedRoomError("This host has too many active Group Chats. Delete one and try again.")
        repo.insert_row(conn, store, rooms, dict(room_id=room_id, name=name, members_json=members_json,
            authority_gateway_id=gateway, authority_epoch=1, next_seq=1, event_bytes=0, revision=1,
            created_at=timestamp, updated_at=timestamp, disbanded_at=None))
        row = repo.room(conn, store, room_id)
    # Native creation does not publish a latest_seq field until the subsequent state read.
    row.pop("next_seq")
    return {**native._room_from_row(row), "members": normalized}


def append_on_connection(conn, store, room, *, event_id, kind, actor_json, payload_json, epoch, now, allow_control=False, **changes):
    size = event_size(conn, store, room, event_id, kind, actor_json, payload_json, allow_control=allow_control)
    row = dict(room_id=room["room_id"], seq=room["next_seq"], event_id=event_id, kind=kind, actor_json=actor_json,
               authority_epoch=epoch, payload_json=payload_json, created_at=now)
    repo.insert_row(conn, store, events, row)
    repo.change_room(conn, store, room["room_id"], next_seq=room["next_seq"] + 1,
                     event_bytes=room["event_bytes"] + size, updated_at=now, **changes)
    return row


def _publication_fields(room_id, event_id, kind, actor, gateway, epoch, cursor):
    room_id, event_id = native._room_id(room_id), native._event_id(event_id)
    if cursor is not None:
        native._bounded_int(cursor, message="expected_latest_seq must be a nonnegative integer")
    kind = native._validate_event_kind(kind)
    normalized, actor_json = native._validate_actor(actor, kind=kind)
    gateway = native._actor_id(gateway, "authority_gateway_id")
    if normalized["kind"] == "gateway" and normalized["id"] != gateway:
        raise native.HostedRoomError("gateway actor.id must match authority_gateway_id")
    return room_id, event_id, kind, normalized, actor_json, gateway, native._require_positive_int(epoch, "authority_epoch")


def append_event(store, *, room_id, event_id, kind, actor, payload, authority_gateway_id=None, authority_epoch=None,
                 now=None, expected_latest_seq=None, control_reserve=False):
    room_id, event_id, kind, normalized, actor_json, gateway, epoch = _publication_fields(
        room_id, event_id, kind, actor, authority_gateway_id, authority_epoch, expected_latest_seq)
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        resolved = effects.invoke(payload, conn, store.scope) if isinstance(payload, effects.CoreEffect) or callable(payload) else payload
        if not isinstance(resolved, dict):
            raise native.HostedRoomError("payload must be an object")
        payload_json = native._payload_json(resolved)
        existing = repo.event(conn, store, room_id, event_id)
        if existing is not None:
            if native._event_content(existing) != (kind, actor_json, epoch, payload_json):
                raise native.EventConflictError("event_id already exists with different immutable content")
            return native._event_from_row(existing, idempotent=True)
        room = repo.room(conn, store, room_id, lock=True)
        native._require_authority(room, gateway, epoch, "stale hosted room authority")
        if expected_latest_seq is not None and room["next_seq"] - 1 != expected_latest_seq:
            raise native.EventCursorConflictError("room changed before event publication")
        if kind in {"message.user", "message.member"}:
            from hermes_db.operations.room_attachment_commits import retain_message_attachments
            retain_message_attachments(conn, store, room_id=room_id, event_id=event_id,
                manifest=resolved.get("attachments", []), now=timestamp)
        row = append_on_connection(conn, store, room, event_id=event_id, kind=kind, actor_json=actor_json,
            payload_json=payload_json, epoch=epoch, now=timestamp, allow_control=kind in native._CONTROL_EVENT_KINDS
            or (control_reserve and normalized["kind"] == "gateway"))
    return {**native._event_from_row(row), "actor": normalized}


def rename_room(store, *, room_id, event_id, name, now=None):
    room_id, event_id, name = native._room_id(room_id), native._event_id(event_id), native._validate_room_name(name)
    payload = native._payload_json({"name": name})
    with store.write() as conn:
        repo.lock_store(conn, store)
        room = repo.room(conn, store, room_id, lock=True)
        existing = repo.event(conn, store, room_id, event_id)
        if existing is not None:
            if existing["kind"] != "room.renamed" or existing["payload_json"] != payload:
                raise native.EventConflictError("event_id already exists with different immutable content")
        else:
            existing = append_on_connection(conn, store, room, event_id=event_id, kind="room.renamed",
                actor_json=native._system_actor_json("room-control"), payload_json=payload, epoch=room["authority_epoch"],
                now=clock(now), name=name, revision=room["revision"] + 1)
            room = repo.room(conn, store, room_id)
            return {**native._room_from_row(room), "event": native._event_from_row(existing)}
        return {**native._room_from_row(room, idempotent=True), "event": native._event_from_row(existing, idempotent=True)}
