"""Room lifecycle workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms import rules as _storage_shared_1
from sqlalchemy import func, select, delete
from hermes_db.domains.rooms import rules as op_rooms_native, rules as op_reads_native, rules as op_context_rooms
from hermes_db.domains.rooms.rules import clock
from hermes_db.domains.runtime.postgres.operations import effects
from hermes_db.domains.rooms.postgres import repository as repo
from hermes_db.tables.rooms import rooms as op_rooms_rooms, events, retired, rooms as op_reads_rooms, rooms as op_retention_rooms, links, reservations, remote_runs
from gateway.hosted_room_pages import replay_page
from hermes_db.core.values import encode_text, decode_text
import json
from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect

def create_room(store, *, room_id, name, members, authority_gateway_id, now=None, admit=None):
    room_id, name = (op_rooms_native._room_id(room_id), op_rooms_native._validate_room_name(name))
    normalized, members_json = op_rooms_native._validate_members(members)
    gateway = op_rooms_native._actor_id(authority_gateway_id, 'authority_gateway_id')
    timestamp = clock(now)
    with store.write() as conn:
        effects.invoke(admit, conn, store.scope)
        repo.lock_store(conn, store)
        if conn.scalar(select(retired.c.room_id).where(repo.scope(retired, store, room_id))) is not None:
            raise op_rooms_native.RoomConflictError('room_id belongs to a disbanded room')
        row = conn.execute(select(op_rooms_rooms).where(repo.scope(op_rooms_rooms, store, room_id)).with_for_update()).mappings().one_or_none()
        if row is not None:
            existing = repo.decode(row)
            if existing['disbanded_at'] is not None:
                raise op_rooms_native.RoomConflictError('room_id belongs to a disbanded room')
            if existing['name'] != name or existing['members_json'] != members_json:
                raise op_rooms_native.RoomConflictError('room_id already exists with different state')
            if existing['authority_gateway_id'] != gateway:
                raise op_rooms_native.RoomConflictError('room_id already belongs to a different authority')
            return op_rooms_native._room_from_row(existing, idempotent=True)
        count = conn.scalar(select(func.count()).select_from(op_rooms_rooms).where(repo.scope(op_rooms_rooms, store), op_rooms_rooms.c.disbanded_at.is_(None)))
        if count >= op_rooms_native.MAX_ACTIVE_ROOMS:
            raise op_rooms_native.HostedRoomError('This host has too many active Group Chats. Delete one and try again.')
        repo.insert_row(conn, store, op_rooms_rooms, dict(room_id=room_id, name=name, members_json=members_json, authority_gateway_id=gateway, authority_epoch=1, next_seq=1, event_bytes=0, revision=1, created_at=timestamp, updated_at=timestamp, disbanded_at=None))
        row = repo.room(conn, store, room_id)
    row.pop('next_seq')
    return {**op_rooms_native._room_from_row(row), 'members': normalized}

def append_on_connection(conn, store, room, *, event_id, kind, actor_json, payload_json, epoch, now, allow_control=False, **changes):
    size = event_size(conn, store, room, event_id, kind, actor_json, payload_json, allow_control=allow_control)
    row = dict(room_id=room['room_id'], seq=room['next_seq'], event_id=event_id, kind=kind, actor_json=actor_json, authority_epoch=epoch, payload_json=payload_json, created_at=now)
    repo.insert_row(conn, store, events, row)
    repo.change_room(conn, store, room['room_id'], next_seq=room['next_seq'] + 1, event_bytes=room['event_bytes'] + size, updated_at=now, **changes)
    return row

def _publication_fields(room_id, event_id, kind, actor, gateway, epoch, cursor):
    room_id, event_id = (op_rooms_native._room_id(room_id), op_rooms_native._event_id(event_id))
    if cursor is not None:
        op_rooms_native._bounded_int(cursor, message='expected_latest_seq must be a nonnegative integer')
    kind = op_rooms_native._validate_event_kind(kind)
    normalized, actor_json = op_rooms_native._validate_actor(actor, kind=kind)
    gateway = op_rooms_native._actor_id(gateway, 'authority_gateway_id')
    if normalized['kind'] == 'gateway' and normalized['id'] != gateway:
        raise op_rooms_native.HostedRoomError('gateway actor.id must match authority_gateway_id')
    return (room_id, event_id, kind, normalized, actor_json, gateway, op_rooms_native._require_positive_int(epoch, 'authority_epoch'))

def append_event(store, *, room_id, event_id, kind, actor, payload, authority_gateway_id=None, authority_epoch=None, now=None, expected_latest_seq=None, control_reserve=False):
    room_id, event_id, kind, normalized, actor_json, gateway, epoch = _publication_fields(room_id, event_id, kind, actor, authority_gateway_id, authority_epoch, expected_latest_seq)
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        resolved = effects.invoke(payload, conn, store.scope) if isinstance(payload, effects.CoreEffect) or callable(payload) else payload
        if not isinstance(resolved, dict):
            raise op_rooms_native.HostedRoomError('payload must be an object')
        payload_json = op_rooms_native._payload_json(resolved)
        existing = repo.event(conn, store, room_id, event_id)
        if existing is not None:
            if op_rooms_native._event_content(existing) != (kind, actor_json, epoch, payload_json):
                raise op_rooms_native.EventConflictError('event_id already exists with different immutable content')
            return op_rooms_native._event_from_row(existing, idempotent=True)
        room = repo.room(conn, store, room_id, lock=True)
        op_rooms_native._require_authority(room, gateway, epoch, 'stale hosted room authority')
        if expected_latest_seq is not None and room['next_seq'] - 1 != expected_latest_seq:
            raise op_rooms_native.EventCursorConflictError('room changed before event publication')
        if kind in {'message.user', 'message.member'}:
            from hermes_db.domains.rooms.attachments.postgres.metadata import retain_message_attachments
            retain_message_attachments(conn, store, room_id=room_id, event_id=event_id, manifest=resolved.get('attachments', []), now=timestamp)
        row = append_on_connection(conn, store, room, event_id=event_id, kind=kind, actor_json=actor_json, payload_json=payload_json, epoch=epoch, now=timestamp, allow_control=kind in op_rooms_native._CONTROL_EVENT_KINDS or (control_reserve and normalized['kind'] == 'gateway'))
    return {**op_rooms_native._event_from_row(row), 'actor': normalized}

def rename_room(store, *, room_id, event_id, name, now=None):
    room_id, event_id, name = (op_rooms_native._room_id(room_id), op_rooms_native._event_id(event_id), op_rooms_native._validate_room_name(name))
    payload = op_rooms_native._payload_json({'name': name})
    with store.write() as conn:
        repo.lock_store(conn, store)
        room = repo.room(conn, store, room_id, lock=True)
        existing = repo.event(conn, store, room_id, event_id)
        if existing is not None:
            if existing['kind'] != 'room.renamed' or existing['payload_json'] != payload:
                raise op_rooms_native.EventConflictError('event_id already exists with different immutable content')
        else:
            existing = append_on_connection(conn, store, room, event_id=event_id, kind='room.renamed', actor_json=op_rooms_native._system_actor_json('room-control'), payload_json=payload, epoch=room['authority_epoch'], now=clock(now), name=name, revision=room['revision'] + 1)
            room = repo.room(conn, store, room_id)
            return {**op_rooms_native._room_from_row(room), 'event': op_rooms_native._event_from_row(existing)}
        return {**op_rooms_native._room_from_row(room, idempotent=True), 'event': op_rooms_native._event_from_row(existing, idempotent=True)}

def list_rooms(store, *, include_disbanded=False, limit=op_reads_native.MAX_ROOM_LIST_LIMIT, offset=0):
    limit = op_reads_native._bounded_limit(limit, op_reads_native.MAX_ROOM_LIST_LIMIT)
    offset = op_reads_native._non_negative(offset, 'offset')
    statement = select(op_reads_rooms).where(repo.scope(op_reads_rooms, store))
    if not include_disbanded:
        statement = statement.where(op_reads_rooms.c.disbanded_at.is_(None))
    with store.read() as conn:
        return [op_reads_native._room_from_row(repo.decode(row)) for row in conn.execute(statement.order_by(op_reads_rooms.c.updated_at.desc(), op_reads_rooms.c.room_id).limit(limit).offset(offset)).mappings()]

def room_state(store, *, room_id, include_disbanded=False):
    room_id = op_reads_native._room_id(room_id)
    with store.read() as conn:
        room = repo.room(conn, store, room_id, include_disbanded=include_disbanded)
        claim = conn.execute(select(events).where(repo.scope(events, store, room_id), events.c.kind == encode_text('authority.claimed'), events.c.authority_epoch == room['authority_epoch']).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    return {**op_reads_native._room_from_row(room), **({'authority_claim': op_reads_native._event_from_row(repo.decode(claim))} if claim else {})}

def probe_hosted_room(store, *, room_id):
    with store.read() as conn:
        return conn.scalar(select(op_reads_rooms.c.room_id).where(repo.scope(op_reads_rooms, store, op_reads_native._room_id(room_id)), op_reads_rooms.c.disbanded_at.is_(None))) is not None

def read_events(store, *, room_id, since_seq=0, limit=100, include_disbanded=False):
    room_id = op_reads_native._room_id(room_id)
    since_seq = op_reads_native._non_negative(since_seq, 'since_seq')
    limit = op_reads_native._bounded_limit(limit, op_reads_native.MAX_LOG_LIMIT)
    with store.read() as conn:
        room = repo.room(conn, store, room_id, include_disbanded=include_disbanded)
        latest = room['next_seq'] - 1
        if since_seq > latest:
            raise op_reads_native.HostedRoomError('since_seq is ahead of the hosted room log')
        size = sum(func.octet_length(events.c[key]) for key in ('event_id', 'kind', 'actor_json', 'payload_json'))
        candidates = select(events, func.sum(size).over(order_by=events.c.seq).label('cumulative_bytes')).where(repo.scope(events, store, room_id), events.c.seq > since_seq).order_by(events.c.seq).limit(limit).subquery()
        rows = [op_reads_native._event_from_row(repo.decode(row)) for row in conn.execute(select(candidates).where(candidates.c.cumulative_bytes <= op_reads_native.MAX_LOG_PAGE_BYTES).order_by(candidates.c.seq)).mappings()]
    return replay_page(rows, since_seq=since_seq, latest_seq=latest, authority={'gateway_id': room['authority_gateway_id'], 'epoch': room['authority_epoch']}, max_bytes=op_reads_native.MAX_LOG_PAGE_BYTES, error=op_reads_native.HostedRoomError)

def prune_locked(conn, store, *, now=None, max_gateway_event_bytes=None):
    from hermes_db.domains.rooms import rules as native
    statement = select(op_retention_rooms.c.room_id, op_retention_rooms.c.disbanded_at, op_retention_rooms.c.event_bytes).where(repo.scope(op_retention_rooms, store), op_retention_rooms.c.disbanded_at.is_not(None)).order_by(op_retention_rooms.c.disbanded_at.desc(), op_retention_rooms.c.room_id)
    rows = list(conn.execute(statement).mappings())
    selected = {row['room_id'] for index, row in enumerate(rows) if index >= native.MAX_DISBANDED_ROOM_TOMBSTONES or (now is not None and row['disbanded_at'] <= now - native.DISBANDED_ROOM_RETENTION_SECONDS)}
    if max_gateway_event_bytes is not None:
        total = repo.gateway_bytes(conn, store)
        for row in reversed(rows):
            if total <= max_gateway_event_bytes:
                break
            selected.add(row['room_id'])
            total -= row['event_bytes']
    for row in rows:
        if row['room_id'] in selected:
            repo.retire(conn, store, row['room_id'], row['disbanded_at'])
    if selected:
        for table in (links, reservations, remote_runs):
            keys = [repo.values(table, {'room_id': room_id})['room_id'] for room_id in selected]
            conn.execute(delete(table).where(repo.scope(table, store), table.c.room_id.in_(keys)))
        conn.execute(delete(op_retention_rooms).where(repo.scope(op_retention_rooms, store), op_retention_rooms.c.room_id.in_(selected)))
    return len(selected)

def prune_disbanded_rooms(store, *, now=None):
    from hermes_db.domains.rooms.rules import clock
    with store.write() as conn:
        repo.lock_store(conn, store)
        return prune_locked(conn, store, now=clock(now))

def event_size(conn, store, room, event_id, kind, actor_json, payload_json, *, allow_control=False):
    from hermes_db.domains.rooms import rules as native
    from hermes_db.domains.rooms.rules import utf8_len
    size = utf8_len(event_id, kind, actor_json, payload_json)
    count_reserve = native.CONTROL_EVENT_COUNT_RESERVE if allow_control else 0
    byte_reserve = native.CONTROL_EVENT_BYTE_RESERVE if allow_control else 0
    if room['next_seq'] - 1 >= native.MAX_EVENTS_PER_ROOM + count_reserve:
        raise native.HostedRoomError('This Group Chat reached its history limit. Start a new Group Chat to continue.')
    if room['event_bytes'] + size > native.MAX_ROOM_EVENT_BYTES + byte_reserve:
        raise native.HostedRoomError('This Group Chat reached its storage limit. Start a new Group Chat to continue.')
    limit = native.MAX_GATEWAY_EVENT_BYTES + byte_reserve
    if repo.gateway_bytes(conn, store) + size > limit:
        prune_locked(conn, store, max_gateway_event_bytes=max(0, limit - size))
    if repo.gateway_bytes(conn, store) + size > limit:
        raise native.HostedRoomError('Group Chat storage is full on this host. Delete an old Group Chat and try again.')
    return size

def _latest(conn, store, room_id, before_seq):
    statement = select(events.c.payload_json).where(repo.scope(events, store, room_id), events.c.kind == encode_text(_storage_shared_1.CONTEXT_EVENT_KIND))
    if before_seq is not None:
        statement = statement.where(events.c.seq < int(before_seq))
    raw = conn.scalar(statement.order_by(events.c.seq.desc()).limit(1))
    if raw is None:
        return dict(_storage_shared_1._EMPTY_CONTEXT)
    payload = json.loads(decode_text(raw))
    return {key: str(payload.get(key) or default) for key, default in _storage_shared_1._EMPTY_CONTEXT.items()}

def room_context(store, *, room_id, before_seq=None):
    room_id = op_context_rooms._room_id(room_id)
    with store.read() as conn:
        return _latest(conn, store, room_id, before_seq)

def set_room_context(store, *, room_id, event_id, purpose, notes, routing=None, lead_member_id=None, now=None):
    state = room_state(store, room_id=room_id)
    if state["authority_gateway_id"] != store.local_authority_gateway_id():
        raise op_context_rooms.AuthorityConflictError("This Group Chat is managed by another gateway.")
    seated = {str(member.get('member_id')) for member in state.get('members') or ()}
    saved = {}

    def settings(conn, scope):
        first = repo.event(conn, store, state['room_id'], op_context_rooms._event_id(event_id))
        original = json.loads(first['payload_json']) if first is not None and first['kind'] == _storage_shared_1.CONTEXT_EVENT_KIND else None
        current = {**_storage_shared_1._EMPTY_CONTEXT, **original} if original is not None else _latest(conn, store, state['room_id'], None)
        context = _storage_shared_1.validate_context(purpose, notes, current['routing'] if routing is None else routing, current['lead_member_id'] if lead_member_id is None else lead_member_id)
        if first is None and context['routing'] == 'lead' and (context['lead_member_id'] not in seated):
            raise op_context_rooms.HostedRoomError('the lead must be a member of this Group Chat')
        saved.update(context)
        if original is None:
            return context
        return {key: value for key, value in context.items() if key in original or value != _storage_shared_1._EMPTY_CONTEXT[key]}
    event = append_event(store, room_id=room_id, event_id=event_id, kind=_storage_shared_1.CONTEXT_EVENT_KIND, actor=dict(_storage_shared_1._CONTEXT_ACTOR), payload=CoreEffect(settings), authority_gateway_id=state['authority_gateway_id'], authority_epoch=state['authority_epoch'], now=now)
    return {'context': saved, 'event': event}
