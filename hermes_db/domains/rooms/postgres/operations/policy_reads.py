"""Exact publication identities and admitted-task history reconstruction."""

from sqlalchemy import select
from gateway import hosted_room_policy_checkpoint as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, policy as repo
from hermes_db.tables.rooms import events
from hermes_db.tables.room_work import publications
from hermes_db.core.values import encode_text


def publication_exists(store, *, room_id, task_id, status, execution_generation):
    statement = select(publications.c.seq).where(room_repo.key(publications, store, dict(room_id=room_id, task_id=task_id)))
    if status == "deferred":
        statement = statement.where(publications.c.kind == "turn.deferred", publications.c.execution_generation == execution_generation)
    else:
        statement = statement.where(publications.c.kind.in_(("turn.settled", "turn.failed", "turn.cancelled")))
    with store.read() as conn:
        return conn.scalar(statement.limit(1)) is not None


def _published_task_events(conn, store, room_id, task_id):
    if not task_id:
        return []
    digest = task_id.removeprefix("dtask:")
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.event_id.in_(
        [encode_text("dmessage:" + digest), encode_text("dterminal:" + digest)])).order_by(events.c.seq)).mappings()
    result = [repo.event_values(row) for row in rows]
    if any(event["payload"].get("task_id") != task_id for event in result):
        raise RuntimeError("published task receipt identity changed")
    return result


def _frozen_events(conn, store, room_id, source_seq, context, published):
    context = native.validate_task_input(context)
    seqs = sorted({source_seq, *context["event_seqs"]})
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq.in_(seqs)).order_by(events.c.seq)).mappings().all()
    if len(rows) != len(seqs):
        raise RuntimeError("admitted task input event is missing")
    selected = {row["seq"]: repo.event_values(row) for row in rows}
    source = selected[source_seq]
    thread = native._text(source["payload"], "thread_id")
    if source["kind"] != "message.user" or not thread:
        raise RuntimeError("admitted task source is not a user discussion")
    latest = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.kind == encode_text("message.user"),
        events.c.policy_thread_key == encode_text(thread)).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    if latest is not None:
        selected[latest["seq"]] = repo.event_values(latest)
    selected.update({event["seq"]: event for event in published})
    return [selected[seq] for seq in sorted(selected)]


def events_for_task(store, *, room_id, source_event_seq, input_context=None, task_id=None, max_active, max_transcript):
    with store.read() as conn:
        published = _published_task_events(conn, store, room_id, task_id)
        if input_context is not None:
            return _frozen_events(conn, store, room_id, source_event_seq, input_context, published)
        source = repo.source_event(conn, store, room_id, source_event_seq)
        if source is None or source["kind"] != "message.user":
            return published
        selected = repo.discussion_events(conn, store, room_id=room_id, thread_id=native._text(source["payload"], "thread_id"),
            discussion_event_id=source["event_id"], max_active=max_active, max_transcript=max_transcript, bound_error="task policy projection exceeded its bound")
        merged = {event["seq"]: event for event in [*selected, *published, source]}
        return [merged[seq] for seq in sorted(merged)]
