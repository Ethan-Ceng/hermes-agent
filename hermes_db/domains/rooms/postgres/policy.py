"""Room policy workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms import rules as _storage_shared_1
from gateway import hosted_room_task_input as _storage_shared_2
from sqlalchemy import delete, func, select, update, union_all
from hermes_db.domains.rooms import rules as hosted_rooms, rules as rows_policy_native
from hermes_db.domains.rooms.postgres import repository as room_repo
from hermes_db.tables.room_policy import capacity, cursors, transcript_state, threads, active, watermarks, transcript
from collections.abc import Mapping
from hermes_db.tables.rooms import events
from hermes_db.tables.room_work import publications
from hermes_db.core.values import encode_text, decode_text
import json
from sqlalchemy.dialects.postgresql import insert

def initialize(store, requested):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        upsert(conn, store, capacity, dict(singleton=1, max_active_events=requested), lambda excluded: dict(max_active_events=func.greatest(capacity.c.max_active_events, excluded.max_active_events)))
        return conn.scalar(select(capacity.c.max_active_events).where(room_repo.scope(capacity, store), capacity.c.singleton == 1))

def ensure_cursor(store, room_id):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
        insert_ignore(conn, store, cursors, dict(room_id=room_id, through_seq=0, stopped_through_seq=0, updated_at=0))
        version = conn.scalar(select(transcript_state.c.schema_version).where(room_repo.scope(transcript_state, store, room_id)))
        if version is None or version < _storage_shared_1._TRANSCRIPT_SCHEMA_VERSION:
            for table in (active, threads, watermarks, transcript):
                conn.execute(delete(table).where(room_repo.scope(table, store, room_id)))
            conn.execute(update(cursors).where(room_repo.scope(cursors, store, room_id)).values(through_seq=0, stopped_through_seq=0))
            upsert(conn, store, transcript_state, dict(room_id=room_id, schema_version=_storage_shared_1._TRANSCRIPT_SCHEMA_VERSION), lambda excluded: dict(schema_version=excluded.schema_version))
        cursor = conn.scalar(select(cursors.c.through_seq).where(room_repo.scope(cursors, store, room_id)))
        if cursor >= room['next_seq']:
            raise RuntimeError('room policy cursor is ahead of the durable log')
        return cursor

def apply_page(store, room_id, expected, rows, next_cursor):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
        current = conn.scalar(select(cursors.c.through_seq).where(room_repo.scope(cursors, store, room_id)).with_for_update())
        if current is None:
            raise RuntimeError('room policy cursor disappeared during replay')
        if current != expected:
            return current
        for event in rows:
            apply_event(conn, store, event)
        changed = conn.execute(update(cursors).where(room_repo.scope(cursors, store, room_id), cursors.c.through_seq == expected).values(through_seq=next_cursor, updated_at=float(rows[-1].get('created_at') or 0)))
        if changed.rowcount != 1:
            raise RuntimeError('room policy cursor disappeared during replay')
    return next_cursor

def snapshot(store, room_id, *, max_active, max_transcript):
    with store.read() as conn:
        cursor = conn.execute(select(cursors).where(room_repo.scope(cursors, store, room_id))).mappings().one_or_none()
        if cursor is None:
            raise hosted_rooms.RoomNotFoundError('hosted room checkpoint not found')
        thread = conn.execute(select(threads).where(room_repo.scope(threads, store, room_id), threads.c.completed == 0, threads.c.latest_user_seq > cursor['stopped_through_seq']).order_by(threads.c.latest_user_seq, threads.c.thread_id).limit(1)).mappings().one_or_none()
        if thread is None:
            return _storage_shared_1.PolicySnapshot(cursor['through_seq'], cursor['stopped_through_seq'], (), {})
        thread = room_repo.decode(thread)
        events = discussion_events(conn, store, room_id=room_id, thread_id=thread['thread_id'], discussion_event_id=thread['discussion_event_id'], max_active=max_active, max_transcript=max_transcript, bound_error='active room policy projection exceeded its bound')
        rows = [room_repo.decode(row) for row in conn.execute(select(watermarks).where(room_repo.key(watermarks, store, dict(room_id=room_id, thread_id=thread['thread_id'])))).mappings()]
        return _storage_shared_1.PolicySnapshot(cursor['through_seq'], cursor['stopped_through_seq'], tuple(events), {(thread['thread_id'], row['member_id']): row['seen_through_seq'] for row in rows})

def compact_completed(store, room_id):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        completed = select(threads.c.discussion_event_id).where(room_repo.scope(threads, store, room_id), threads.c.completed == 1)
        conn.execute(delete(active).where(room_repo.scope(active, store, room_id), active.c.discussion_event_id.in_(completed)))
        conn.execute(delete(threads).where(room_repo.scope(threads, store, room_id), threads.c.completed == 1))

def _thread(conn, store, event, thread_id, discussion_id):
    fields = dict(room_id=event['room_id'], thread_id=thread_id, discussion_event_id=discussion_id, latest_user_seq=int(event['seq']), completed=0)
    upsert(conn, store, threads, fields, lambda excluded: {key: excluded[key] for key in ('discussion_event_id', 'latest_user_seq', 'completed')})

def user_message(conn, store, event, payload):
    thread, discussion = (_storage_shared_1._text(payload, 'thread_id'), _storage_shared_1._text(event, 'event_id'))
    if not thread or not discussion:
        return
    _thread(conn, store, event, thread, discussion)
    store_active(conn, store, event, thread, discussion)
    store_transcript(conn, store, event, thread)

def discussion_event(conn, store, event, payload):
    room_id, kind, seq = (event['room_id'], event['kind'], int(event['seq']))
    thread, discussion = (_storage_shared_1._text(payload, 'thread_id'), _storage_shared_1._text(payload, 'discussion_event_id'))
    if conn.scalar(select(active.c.seq).where(room_repo.scope(active, store, room_id), active.c.discussion_event_id == encode_text(discussion)).limit(1)) is not None:
        store_active(conn, store, event, thread, discussion)
    if kind not in _storage_shared_1._TERMINAL_KINDS:
        return
    task_id = _storage_shared_1._text(payload, 'task_id')
    generation = int(payload.get('execution_generation') or 0) if kind == 'turn.deferred' else 0
    if task_id:
        insert_ignore(conn, store, publications, dict(room_id=room_id, task_id=task_id, kind=kind, execution_generation=generation, seq=seq))
    member, seen = (_storage_shared_1._text(payload, 'member_id'), int(payload.get('seen_through_seq') or 0))
    if kind == 'turn.settled' and payload.get('message_event_id'):
        message = room_repo.event(conn, store, room_id, payload['message_event_id'])
        if message is not None:
            committed = event_values(message)
            if committed['kind'] == 'message.member' and _storage_shared_1._text(committed['payload'], 'discussion_event_id') == discussion:
                seen = max(seen, int(committed['seq']))
                store_transcript(conn, store, committed, thread, seq)
    else:
        store_transcript(conn, store, event, thread)
    if member and seen > 0:
        upsert(conn, store, watermarks, dict(room_id=room_id, thread_id=thread, member_id=member, seen_through_seq=seen), lambda excluded: dict(seen_through_seq=func.greatest(watermarks.c.seen_through_seq, excluded.seen_through_seq)))

def room_activity(conn, store, event, payload):
    conn.execute(delete(active).where(room_repo.key(active, store, dict(room_id=event['room_id'], discussion_event_id=_storage_shared_1._text(payload, 'discussion_event_id')))))
    conn.execute(delete(threads).where(room_repo.key(threads, store, dict(room_id=event['room_id'], thread_id=_storage_shared_1._text(payload, 'thread_id'), discussion_event_id=_storage_shared_1._text(payload, 'discussion_event_id')))))

def continued(conn, store, event, payload):
    room_id, discussion = (event['room_id'], _storage_shared_1._text(payload, 'discussion_event_id'))
    row = room_repo.event(conn, store, room_id, discussion)
    if row is None or row['kind'] != 'message.user':
        return
    source = event_values(row)
    thread = _storage_shared_1._text(source['payload'], 'thread_id')
    newer = conn.scalar(select(events.c.seq).where(room_repo.scope(events, store, room_id), events.c.seq > int(source['seq']), events.c.seq <= int(event['seq']), events.c.kind == encode_text('message.user'), events.c.policy_thread_key == encode_text(thread)).limit(1))
    if newer is not None:
        return
    _thread(conn, store, source, thread, discussion)
    store_active(conn, store, source, thread, discussion)
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq > int(source['seq']), events.c.seq <= int(event['seq']), events.c.kind.in_([encode_text(kind) for kind in _storage_shared_1._REOPENED_KINDS]), events.c.policy_discussion_key == encode_text(discussion)).order_by(events.c.seq)).mappings()
    for row in rows:
        store_active(conn, store, event_values(row), thread, discussion)

def stop_requested(conn, store, event, payload):
    conn.execute(update(cursors).where(room_repo.scope(cursors, store, event['room_id'])).values(stopped_through_seq=func.greatest(cursors.c.stopped_through_seq, int(event['seq']))))
HANDLERS = {'message.user': user_message, 'message.member': discussion_event, **dict.fromkeys(_storage_shared_1._TERMINAL_KINDS, discussion_event), 'room.activity': room_activity, 'room.assignment': discussion_event, 'room.routed': discussion_event, 'room.continued': continued, 'room.stop_requested': stop_requested}

def apply_event(conn, store, event):
    handler = HANDLERS.get(_storage_shared_1._text(event, 'kind'))
    if handler is not None:
        payload = event.get('payload')
        handler(conn, store, event, payload if isinstance(payload, Mapping) else {})

def publication_exists(store, *, room_id, task_id, status, execution_generation):
    statement = select(publications.c.seq).where(room_repo.key(publications, store, dict(room_id=room_id, task_id=task_id)))
    if status == 'deferred':
        statement = statement.where(publications.c.kind == 'turn.deferred', publications.c.execution_generation == execution_generation)
    else:
        statement = statement.where(publications.c.kind.in_(('turn.settled', 'turn.failed', 'turn.cancelled')))
    with store.read() as conn:
        return conn.scalar(statement.limit(1)) is not None

def _published_task_events(conn, store, room_id, task_id):
    if not task_id:
        return []
    digest = task_id.removeprefix('dtask:')
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.event_id.in_([encode_text('dmessage:' + digest), encode_text('dterminal:' + digest)])).order_by(events.c.seq)).mappings()
    result = [event_values(row) for row in rows]
    if any(event['payload'].get('task_id') != task_id for event in result):
        raise RuntimeError('published task receipt identity changed')
    return result

def _frozen_events(conn, store, room_id, source_seq, context, published):
    context = _storage_shared_2.validate_task_input(context)
    seqs = sorted({source_seq, *context['event_seqs']})
    rows = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq.in_(seqs)).order_by(events.c.seq)).mappings().all()
    if len(rows) != len(seqs):
        raise RuntimeError('admitted task input event is missing')
    selected = {row['seq']: event_values(row) for row in rows}
    source = selected[source_seq]
    thread = _storage_shared_1._text(source['payload'], 'thread_id')
    if source['kind'] != 'message.user' or not thread:
        raise RuntimeError('admitted task source is not a user discussion')
    latest = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.kind == encode_text('message.user'), events.c.policy_thread_key == encode_text(thread)).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    if latest is not None:
        selected[latest['seq']] = event_values(latest)
    selected.update({event['seq']: event for event in published})
    return [selected[seq] for seq in sorted(selected)]

def events_for_task(store, *, room_id, source_event_seq, input_context=None, task_id=None, max_active, max_transcript):
    with store.read() as conn:
        published = _published_task_events(conn, store, room_id, task_id)
        if input_context is not None:
            return _frozen_events(conn, store, room_id, source_event_seq, input_context, published)
        source = source_event(conn, store, room_id, source_event_seq)
        if source is None or source['kind'] != 'message.user':
            return published
        selected = discussion_events(conn, store, room_id=room_id, thread_id=_storage_shared_1._text(source['payload'], 'thread_id'), discussion_event_id=source['event_id'], max_active=max_active, max_transcript=max_transcript, bound_error='task policy projection exceeded its bound')
        merged = {event['seq']: event for event in [*selected, *published, source]}
        return [merged[seq] for seq in sorted(merged)]

def insert_ignore(conn, store, table, fields):
    conn.execute(insert(table).values(store_id=store.scope.require_store_id(), **room_repo.values(table, fields)).on_conflict_do_nothing())

def upsert(conn, store, table, fields, changes):
    statement = insert(table).values(store_id=store.scope.require_store_id(), **room_repo.values(table, fields))
    conn.execute(statement.on_conflict_do_update(index_elements=list(table.primary_key.columns), set_=changes(statement.excluded)))

def event_values(row):
    return rows_policy_native._event_from_row(room_repo.decode(row))

def source_event(conn, store, room_id, seq):
    row = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq == seq)).mappings().one_or_none()
    return event_values(row) if row is not None else None

def store_active(conn, store, event, thread_id, discussion_id):
    insert_ignore(conn, store, active, dict(room_id=event['room_id'], thread_id=thread_id, discussion_event_id=discussion_id, seq=int(event['seq']), event_json=_storage_shared_1.compact_json(dict(event)), kind=event['kind']))

def store_transcript(conn, store, event, thread_id, settled_seq=None):
    key = room_repo.key(transcript, store, dict(room_id=event['room_id'], thread_id=thread_id))
    upsert(conn, store, transcript, dict(room_id=event['room_id'], thread_id=thread_id, seq=int(event['seq']), kind=event['kind'], settled_seq=settled_seq), lambda excluded: dict(settled_seq=func.coalesce(excluded.settled_seq, transcript.c.settled_seq)))
    if event['kind'] in {'message.user', 'message.member'}:
        cutoff = conn.scalar(select(transcript.c.seq).where(key, transcript.c.kind.in_(('message.user', 'message.member'))).order_by(transcript.c.seq.desc()).offset(_storage_shared_1.MAX_THREAD_TRANSCRIPT_EVENTS - 1).limit(1))
        if cutoff is not None:
            conn.execute(delete(transcript).where(key, transcript.c.seq < cutoff))

def discussion_events(conn, store, *, room_id, thread_id, discussion_event_id, max_active, max_transcript, bound_error):
    active_rows = []
    for deferred, bound in ((False, max_active), (True, _storage_shared_1.MAX_ACTIVE_RETRY_RECEIPTS)):
        selected = select(active.c.event_json).where(room_repo.scope(active, store, room_id), active.c.discussion_event_id == encode_text(discussion_event_id), (active.c.kind == 'turn.deferred') == deferred).order_by(active.c.seq).limit(bound + 1)
        rows = conn.execute(selected).scalars().all()
        if len(rows) > bound:
            raise RuntimeError(bound_error)
        active_rows.extend(json.loads(decode_text(row)) for row in rows)
    key = room_repo.key(transcript, store, dict(room_id=room_id, thread_id=thread_id))
    references = union_all(select(transcript.c.seq).where(key), select(transcript.c.settled_seq.label('seq')).where(key, transcript.c.settled_seq.is_not(None))).subquery()
    rows = conn.execute(select(events).join(references, events.c.seq == references.c.seq).where(room_repo.scope(events, store, room_id)).order_by(events.c.seq).limit(max_transcript + 1)).mappings().all()
    if len(rows) > max_transcript:
        raise RuntimeError('thread policy transcript exceeded its bound')
    merged = {int(event['seq']): event for event in [*(event_values(row) for row in rows), *active_rows]}
    return [merged[seq] for seq in sorted(merged)]
