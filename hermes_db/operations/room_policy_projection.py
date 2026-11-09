"""Named, incremental policy effects; no SQLite SQL callback execution."""

from collections.abc import Mapping
from sqlalchemy import delete, func, select, update
from gateway import hosted_room_policy_checkpoint as native
from hermes_db.repositories import rooms as room_repo, room_policy as repo
from hermes_db.tables.rooms import events
from hermes_db.tables.room_policy import active, threads, watermarks, cursors
from hermes_db.tables.room_work import publications
from hermes_db.core.values import encode_text


def _thread(conn, store, event, thread_id, discussion_id):
    fields = dict(room_id=event["room_id"], thread_id=thread_id, discussion_event_id=discussion_id,
        latest_user_seq=int(event["seq"]), completed=0)
    repo.upsert(conn, store, threads, fields, lambda excluded: {key: excluded[key] for key in (
        "discussion_event_id", "latest_user_seq", "completed")})


def user_message(conn, store, event, payload):
    thread, discussion = native._text(payload, "thread_id"), native._text(event, "event_id")
    if not thread or not discussion:
        return
    _thread(conn, store, event, thread, discussion)
    repo.store_active(conn, store, event, thread, discussion)
    repo.store_transcript(conn, store, event, thread)


def discussion_event(conn, store, event, payload):
    room_id, kind, seq = event["room_id"], event["kind"], int(event["seq"])
    thread, discussion = native._text(payload, "thread_id"), native._text(payload, "discussion_event_id")
    if conn.scalar(select(active.c.seq).where(room_repo.scope(active, store, room_id), active.c.discussion_event_id == encode_text(discussion)).limit(1)) is not None:
        repo.store_active(conn, store, event, thread, discussion)
    if kind not in native._TERMINAL_KINDS:
        return
    task_id = native._text(payload, "task_id")
    generation = int(payload.get("execution_generation") or 0) if kind == "turn.deferred" else 0
    if task_id:
        repo.insert_ignore(conn, store, publications, dict(room_id=room_id, task_id=task_id, kind=kind, execution_generation=generation, seq=seq))
    member, seen = native._text(payload, "member_id"), int(payload.get("seen_through_seq") or 0)
    if kind == "turn.settled" and payload.get("message_event_id"):
        message = room_repo.event(conn, store, room_id, payload["message_event_id"])
        if message is not None:
            committed = repo.event_values(message)
            if committed["kind"] == "message.member" and native._text(committed["payload"], "discussion_event_id") == discussion:
                seen = max(seen, int(committed["seq"]))
                repo.store_transcript(conn, store, committed, thread, seq)
    else:
        repo.store_transcript(conn, store, event, thread)
    if member and seen > 0:
        repo.upsert(conn, store, watermarks, dict(room_id=room_id, thread_id=thread, member_id=member, seen_through_seq=seen),
            lambda excluded: dict(seen_through_seq=func.greatest(watermarks.c.seen_through_seq, excluded.seen_through_seq)))


def room_activity(conn, store, event, payload):
    conn.execute(delete(active).where(room_repo.key(active, store, dict(room_id=event["room_id"],
        discussion_event_id=native._text(payload, "discussion_event_id")))))
    conn.execute(delete(threads).where(room_repo.key(threads, store, dict(room_id=event["room_id"],
        thread_id=native._text(payload, "thread_id"), discussion_event_id=native._text(payload, 'discussion_event_id')))))


def continued(conn, store, event, payload):
    room_id, discussion = event["room_id"], native._text(payload, "discussion_event_id")
    row = room_repo.event(conn, store, room_id, discussion)
    if row is None or row["kind"] != "message.user":
        return
    source = repo.event_values(row)
    thread = native._text(source["payload"], "thread_id")
    newer = conn.scalar(select(events.c.seq).where(room_repo.scope(events, store, room_id),
        events.c.seq > int(source['seq']), events.c.seq <= int(event['seq']),
        events.c.kind == encode_text('message.user'), events.c.policy_thread_key == encode_text(thread)).limit(1))
    if newer is not None:
        return
    _thread(conn, store, source, thread, discussion)
    repo.store_active(conn, store, source, thread, discussion)
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq > int(source["seq"]),
        events.c.seq <= int(event["seq"]), events.c.kind.in_([encode_text(kind) for kind in native._REOPENED_KINDS]),
        events.c.policy_discussion_key == encode_text(discussion)).order_by(events.c.seq)).mappings()
    for row in rows:
        repo.store_active(conn, store, repo.event_values(row), thread, discussion)


def stop_requested(conn, store, event, payload):
    conn.execute(update(cursors).where(room_repo.scope(cursors, store, event["room_id"])).values(
        stopped_through_seq=func.greatest(cursors.c.stopped_through_seq, int(event["seq"]))))


HANDLERS = {"message.user": user_message, "message.member": discussion_event,
    **dict.fromkeys(native._TERMINAL_KINDS, discussion_event), "room.activity": room_activity,
    "room.assignment": discussion_event, "room.routed": discussion_event, "room.continued": continued, "room.stop_requested": stop_requested}


def apply_event(conn, store, event):
    handler = HANDLERS.get(native._text(event, "kind"))
    if handler is not None:
        payload = event.get("payload")
        handler(conn, store, event, payload if isinstance(payload, Mapping) else {})
