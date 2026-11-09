"""Snapshot reads preserve the room's authority and log cursor in the same view."""

from sqlalchemy import func, select
from gateway import hosted_rooms as native
from gateway.hosted_room_pages import replay_page
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.rooms import rooms, events
from hermes_db.core.values import encode_text


def list_rooms(store, *, include_disbanded=False, limit=native.MAX_ROOM_LIST_LIMIT, offset=0):
    limit = native._bounded_limit(limit, native.MAX_ROOM_LIST_LIMIT)
    offset = native._non_negative(offset, "offset")
    statement = select(rooms).where(repo.scope(rooms, store))
    if not include_disbanded:
        statement = statement.where(rooms.c.disbanded_at.is_(None))
    with store.read() as conn:
        return [native._room_from_row(repo.decode(row)) for row in conn.execute(statement.order_by(
            rooms.c.updated_at.desc(), rooms.c.room_id).limit(limit).offset(offset)).mappings()]


def room_state(store, *, room_id, include_disbanded=False):
    room_id = native._room_id(room_id)
    with store.read() as conn:
        room = repo.room(conn, store, room_id, include_disbanded=include_disbanded)
        claim = conn.execute(select(events).where(repo.scope(events, store, room_id), events.c.kind == encode_text("authority.claimed"),
            events.c.authority_epoch == room["authority_epoch"]).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    return {**native._room_from_row(room), **({"authority_claim": native._event_from_row(repo.decode(claim))} if claim else {})}


def probe_hosted_room(store, *, room_id):
    with store.read() as conn:
        return conn.scalar(select(rooms.c.room_id).where(repo.scope(rooms, store, native._room_id(room_id)),
            rooms.c.disbanded_at.is_(None))) is not None


def read_events(store, *, room_id, since_seq=0, limit=100, include_disbanded=False):
    room_id = native._room_id(room_id)
    since_seq = native._non_negative(since_seq, "since_seq")
    limit = native._bounded_limit(limit, native.MAX_LOG_LIMIT)
    with store.read() as conn:
        room = repo.room(conn, store, room_id, include_disbanded=include_disbanded)
        latest = room["next_seq"] - 1
        if since_seq > latest:
            raise native.HostedRoomError("since_seq is ahead of the hosted room log")
        size = sum(func.octet_length(events.c[key]) for key in ("event_id", "kind", "actor_json", "payload_json"))
        candidates = select(events, func.sum(size).over(order_by=events.c.seq).label("cumulative_bytes")).where(
            repo.scope(events, store, room_id), events.c.seq > since_seq).order_by(events.c.seq).limit(limit).subquery()
        rows = [native._event_from_row(repo.decode(row)) for row in conn.execute(select(candidates).where(
            candidates.c.cumulative_bytes <= native.MAX_LOG_PAGE_BYTES).order_by(candidates.c.seq)).mappings()]
    return replay_page(rows, since_seq=since_seq, latest_seq=latest, authority={
        "gateway_id": room["authority_gateway_id"], "epoch": room["authority_epoch"]},
        max_bytes=native.MAX_LOG_PAGE_BYTES, error=native.HostedRoomError)
