"""Fenced authority changes and permanent room retirement share the event transaction."""

from sqlalchemy import select
from gateway import hosted_rooms as native
from gateway.hosted_rooms_common import clock
from hermes_db.domains.rooms.postgres.operations.rooms import append_on_connection
from hermes_db.domains.rooms.postgres.operations.retention import prune_locked
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.rooms import rooms, retired


def claim_authority(store, *, room_id, expected_gateway_id, expected_epoch, new_gateway_id, event_id, now=None):
    room_id, event_id = native._room_id(room_id), native._event_id(event_id)
    previous = native._actor_id(expected_gateway_id, "expected_gateway_id")
    gateway = native._actor_id(new_gateway_id, "new_gateway_id")
    epoch = native._require_positive_int(expected_epoch, "expected_epoch") + 1
    actor, payload = native._system_actor_json("authority-control"), native._claim_payload_json(previous, gateway, epoch)
    with store.write() as conn:
        repo.lock_store(conn, store)
        room = repo.room(conn, store, room_id, lock=True)
        event = repo.event(conn, store, room_id, event_id)
        replay = event is not None
        if replay:
            if native._event_content(event) != ("authority.claimed", actor, epoch, payload):
                raise native.EventConflictError("event_id already exists with different content")
            if room["authority_gateway_id"] != gateway or room["authority_epoch"] != epoch:
                raise native.AuthoritySupersededError("authority claim succeeded but was later superseded")
        else:
            native._require_authority(room, previous, expected_epoch, "hosted room authority changed")
            event = append_on_connection(conn, store, room, event_id=event_id, kind="authority.claimed", actor_json=actor,
                payload_json=payload, epoch=epoch, now=clock(now), allow_control=True,
                authority_gateway_id=gateway, authority_epoch=epoch, revision=room["revision"] + 1)
            room = repo.room(conn, store, room_id)
    return {**native._room_from_row(room, idempotent=replay), "claim_event": native._event_from_row(event, idempotent=replay)}


def _disband_replay(conn, store, room_id, room):
    if room is None:
        timestamp = conn.scalar(select(retired.c.retired_at).where(repo.scope(retired, store, room_id)))
        if timestamp is None:
            raise native.RoomNotFoundError("hosted room not found")
        return {"room_id": room_id, "disbanded_at": float(timestamp), "idempotent": True, "history_expired": True}
    if room["disbanded_at"] is None:
        return None
    repo.retire(conn, store, room_id, room["disbanded_at"])
    event = repo.event(conn, store, room_id, "system:room-disbanded")
    return {"room_id": room_id, "disbanded_at": float(room["disbanded_at"]), "idempotent": True,
            **({"event": native._event_from_row(event, idempotent=True)} if event is not None else {})}


def disband_room(store, *, room_id, expected_gateway_id, expected_epoch, now=None):
    room_id = native._room_id(room_id)
    gateway = native._actor_id(expected_gateway_id, "expected_gateway_id")
    epoch = native._require_positive_int(expected_epoch, "expected_epoch")
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        row = conn.execute(select(rooms).where(repo.scope(rooms, store, room_id)).with_for_update()).mappings().one_or_none()
        room = repo.decode(row) if row is not None else None
        replay = _disband_replay(conn, store, room_id, room)
        if replay is not None:
            return replay
        native._require_authority(room, gateway, epoch, "stale hosted room authority")
        from hermes_db.tables.rooms import owed_revokes
        pending = repo.scope(owed_revokes, store, room_id) & (owed_revokes.c.held == 1)
        if conn.scalar(select(owed_revokes.c.room_id).where(pending, owed_revokes.c.expires_at > timestamp).limit(1)) is not None:
            raise native.RoomHeldGrantsPendingError('Group chat grants still need revoking; retry Disband.')
        conn.execute(owed_revokes.delete().where(pending, owed_revokes.c.expires_at <= timestamp))
        event = append_on_connection(conn, store, room, event_id="system:room-disbanded", kind="room.disbanded",
            actor_json=native._system_actor_json("room-control"), payload_json=native._payload_json({"room_id": room_id}),
            epoch=epoch, now=timestamp, allow_control=True, disbanded_at=timestamp, revision=room["revision"] + 1)
        repo.retire(conn, store, room_id, timestamp)
        from hermes_db.domains.rooms.postgres.operations.member_homes import forget_locked
        forget_locked(conn, store, room_id)
        prune_locked(conn, store, now=timestamp, max_gateway_event_bytes=native.MAX_GATEWAY_EVENT_BYTES)
    return {"room_id": room_id, "disbanded_at": timestamp, "idempotent": False, "event": native._event_from_row(event)}
