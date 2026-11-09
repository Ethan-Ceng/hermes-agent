"""Room replication workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms import replication_rules as _storage_shared_1
import json
from sqlalchemy import delete, func, select, update
from hermes_db.domains.rooms import rules as native
from hermes_db.domains.rooms.rules import clock, utf8_len
from hermes_db.domains.rooms.postgres import repository as repo
from hermes_db.tables.rooms import rooms, events, retired, replicas, replica_events

def _state(conn, store, room_id, *, lock=False):
    statement = select(replicas).where(repo.scope(replicas, store, room_id))
    row = conn.execute(statement.with_for_update() if lock else statement).mappings().one_or_none()
    return repo.decode(row) if row is not None else None

def _save(conn, store, room_id, existing, room_name, members_json, authority, last_seq, latest_seq, size, now):
    fields = dict(name=room_name, members_json=members_json, authority_gateway_id=authority['gateway_id'], authority_epoch=authority['epoch'], last_seq=last_seq, latest_seq=max(last_seq, latest_seq), event_bytes=size, updated_at=now)
    if existing is None:
        repo.insert_row(conn, store, replicas, dict(fields, room_id=room_id, created_at=now))
    else:
        conn.execute(update(replicas).where(repo.scope(replicas, store, room_id)).values(**repo.values(replicas, fields)))

def ingest_page(store, *, room_id, room_name, members, page, now=None):
    room_id, room_name = (native._room_id(room_id), native._validate_room_name(room_name))
    _, members_json = native._validate_members(members)
    source_events, authority = _storage_shared_1._validate_page(page)
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        existing = _state(conn, store, room_id, lock=True)
        count = conn.scalar(select(func.count()).select_from(replicas).where(repo.scope(replicas, store)))
        if existing is None and count >= _storage_shared_1.MAX_REPLICA_ROOMS:
            raise _storage_shared_1.ReplicaError('replica room capacity exhausted')
        stored_epoch, last = (existing['authority_epoch'], existing['last_seq']) if existing else (0, 0)
        if authority['epoch'] < stored_epoch:
            raise _storage_shared_1.ReplicaEpochRegressionError('page authority epoch is older than the stored replica epoch')
        new = [event for event in source_events if event['seq'] > last]
        if new and new[0]['seq'] != last + 1:
            raise _storage_shared_1.ReplicaGapError('page skips sequences the replica has not stored')
        size = (existing['event_bytes'] if existing else 0) + sum(_storage_shared_1._event_bytes(event) for event in new)
        if size > _storage_shared_1.MAX_REPLICA_EVENT_BYTES:
            raise _storage_shared_1.ReplicaError('replica event storage exhausted')
        new_last = new[-1]['seq'] if new else last
        latest = page.get('latest_seq')
        latest = latest if type(latest) is int else new_last
        _save(conn, store, room_id, existing, room_name, members_json, authority, new_last, latest, size, timestamp)
        for event in new:
            repo.insert_row(conn, store, replica_events, dict(room_id=room_id, seq=event['seq'], event_id=event['event_id'], kind=event['kind'], actor_json=native._actor_json(event['actor']), authority_epoch=event.get('authority_epoch'), payload_json=native._payload_json(event['payload']), created_at=float(event.get('created_at') or timestamp)))
    return {'room_id': room_id, 'stored_seq': new_last, 'ingested': len(new), 'authority': authority, 'caught_up': new_last >= max(latest, new_last)}

def replica_state(store, *, room_id):
    with store.read() as conn:
        row = _state(conn, store, native._room_id(room_id))
    if row is None:
        raise _storage_shared_1.ReplicaError('replica not found')
    return {'room_id': row['room_id'], 'name': row['name'], 'members': json.loads(row['members_json']), 'authority': {'gateway_id': row['authority_gateway_id'], 'epoch': row['authority_epoch']}, **{key: row[key] for key in ('last_seq', 'latest_seq', 'event_bytes', 'created_at', 'updated_at')}}

def promote_replica(store, *, room_id, reason='authority-unreachable', now=None):
    room_id = native._room_id(room_id)
    if not isinstance(reason, str) or not reason or len(reason) > 200:
        raise _storage_shared_1.ReplicaError('reason must be a non-empty string of at most 200 chars')
    timestamp, local = (clock(now), store.local_authority_gateway_id())
    with store.write() as conn:
        repo.lock_store(conn, store)
        row = _state(conn, store, room_id, lock=True)
        if row is None:
            raise _storage_shared_1.ReplicaError('replica not found')
        if row['authority_gateway_id'] == local:
            raise _storage_shared_1.ReplicaError('this gateway already holds the room authority')
        if conn.scalar(select(rooms.c.room_id).where(repo.scope(rooms, store, room_id))) is not None:
            raise native.RoomConflictError('room_id already exists in the local authoritative store')
        if conn.scalar(select(retired.c.room_id).where(repo.scope(retired, store, room_id))) is not None:
            raise native.RoomConflictError('room_id belongs to a disbanded room')
        epoch, seq = (row['authority_epoch'] + 1, row['last_seq'] + 1)
        control = _storage_shared_1._control_event('claimed', epoch, {'previous_gateway_id': row['authority_gateway_id'], 'authority_gateway_id': local, 'authority_epoch': epoch, 'promoted_from_replica': True, 'reason': reason})
        repo.insert_row(conn, store, rooms, dict(room_id=room_id, name=row['name'], members_json=row['members_json'], authority_gateway_id=local, authority_epoch=epoch, next_seq=seq + 1, event_bytes=row['event_bytes'] + utf8_len(*control), revision=1, created_at=timestamp, updated_at=timestamp, disbanded_at=None))
        for event in conn.execute(select(replica_events).where(repo.scope(replica_events, store, room_id))).mappings():
            repo.insert_row(conn, store, events, {key: value for key, value in repo.decode(event).items() if key != 'store_id'})
        repo.insert_row(conn, store, events, dict(room_id=room_id, seq=seq, event_id=control[0], kind=control[1], actor_json=control[2], authority_epoch=epoch, payload_json=control[3], created_at=timestamp))
        conn.execute(delete(replicas).where(repo.scope(replicas, store, room_id)))
    return {'room_id': room_id, 'authority_gateway_id': local, 'authority_epoch': epoch, 'previous_gateway_id': row['authority_gateway_id'], 'previous_epoch': row['authority_epoch'], 'claim_seq': seq, 'latest_seq': seq}

def demote_room(store, *, room_id, observed_gateway_id, observed_epoch, now=None):
    room_id = native._room_id(room_id)
    gateway = native._validate_identifier(observed_gateway_id, label='observed_gateway_id', max_chars=native.MAX_ACTOR_ID_CHARS)
    epoch = _storage_shared_1._positive_int(observed_epoch, message='observed_epoch must be a positive integer')
    timestamp, local = (clock(now), store.local_authority_gateway_id())
    with store.write() as conn:
        repo.lock_store(conn, store)
        try:
            room = repo.room(conn, store, room_id, lock=True)
        except native.RoomNotFoundError as error:
            raise _storage_shared_1.ReplicaError('room not found in the local authoritative store') from error
        if room['authority_gateway_id'] == gateway and room['authority_epoch'] == epoch:
            return {'room_id': room_id, 'authority_gateway_id': gateway, 'authority_epoch': epoch, 'idempotent': True}
        if epoch <= room['authority_epoch']:
            raise _storage_shared_1.ReplicaEpochRegressionError('observed epoch does not supersede the stored authority')
        if room['authority_gateway_id'] != local:
            raise _storage_shared_1.ReplicaError('room is not locally authoritative; nothing to demote')
        control = _storage_shared_1._control_event('lost', epoch, {'previous_gateway_id': room['authority_gateway_id'], 'authority_gateway_id': gateway, 'authority_epoch': epoch})
        repo.insert_row(conn, store, events, dict(room_id=room_id, seq=room['next_seq'], event_id=control[0], kind=control[1], actor_json=control[2], authority_epoch=epoch, payload_json=control[3], created_at=timestamp))
        repo.change_room(conn, store, room_id, authority_gateway_id=gateway, authority_epoch=epoch, next_seq=room['next_seq'] + 1, event_bytes=room['event_bytes'] + utf8_len(*control), revision=room['revision'] + 1, updated_at=timestamp)
    return {'room_id': room_id, 'authority_gateway_id': gateway, 'authority_epoch': epoch, 'idempotent': False}
