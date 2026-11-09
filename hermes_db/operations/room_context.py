"""Purpose/routing settings are immutable events with an in-transaction settings effect."""

import json
from sqlalchemy import select
from gateway import hosted_room_context as native, hosted_rooms as rooms
from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
from hermes_db.operations.rooms import append_event
from hermes_db.repositories import rooms as repo
from hermes_db.tables.rooms import events
from hermes_db.core.values import encode_text, decode_text


def _latest(conn, store, room_id, before_seq):
    statement = select(events.c.payload_json).where(repo.scope(events, store, room_id), events.c.kind == encode_text(native.CONTEXT_EVENT_KIND))
    if before_seq is not None:
        statement = statement.where(events.c.seq < int(before_seq))
    raw = conn.scalar(statement.order_by(events.c.seq.desc()).limit(1))
    if raw is None:
        return dict(native._EMPTY_CONTEXT)
    payload = json.loads(decode_text(raw))
    return {key: str(payload.get(key) or default) for key, default in native._EMPTY_CONTEXT.items()}


def room_context(store, *, room_id, before_seq=None):
    room_id = rooms._room_id(room_id)
    with store.read() as conn:
        return _latest(conn, store, room_id, before_seq)


def set_room_context(store, *, room_id, event_id, purpose, notes, routing=None, lead_member_id=None, now=None):
    state = native._local_authority(store, room_id)
    seated = {str(member.get("member_id")) for member in state.get("members") or ()}
    saved = {}
    def settings(conn, scope):
        first = repo.event(conn, store, state["room_id"], rooms._event_id(event_id))
        original = json.loads(first["payload_json"]) if first is not None and first["kind"] == native.CONTEXT_EVENT_KIND else None
        current = {**native._EMPTY_CONTEXT, **original} if original is not None else _latest(conn, store, state["room_id"], None)
        context = native.validate_context(purpose, notes, current["routing"] if routing is None else routing,
            current["lead_member_id"] if lead_member_id is None else lead_member_id)
        if first is None and context["routing"] == "lead" and context["lead_member_id"] not in seated:
            raise rooms.HostedRoomError("the lead must be a member of this Group Chat")
        saved.update(context)
        if original is None:
            return context
        return {key: value for key, value in context.items() if key in original or value != native._EMPTY_CONTEXT[key]}
    event = append_event(store, room_id=room_id, event_id=event_id, kind=native.CONTEXT_EVENT_KIND, actor=dict(native._CONTEXT_ACTOR),
        payload=CoreEffect(settings), authority_gateway_id=state["authority_gateway_id"], authority_epoch=state["authority_epoch"], now=now)
    return {"context": saved, "event": event}
