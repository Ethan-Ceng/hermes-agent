"""Room ownership workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms import driver_rules as _storage_shared_1
from sqlalchemy import select, delete
from hermes_db.domains.rooms import rules as op_authority_native, rules as op_coordination_native
from hermes_db.domains.rooms.rules import clock
from hermes_db.domains.rooms.postgres.lifecycle import append_on_connection
from hermes_db.domains.rooms.postgres.lifecycle import prune_locked
from hermes_db.domains.rooms.postgres import repository as op_authority_repo, repository as room_repo, repository as op_leases_repo, repository as room_runs
from hermes_db.tables.rooms import rooms, retired
import dataclasses
from hermes_db.tables.room_runs import leases, tasks
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.values import RuntimeStoreError
import json
from pathlib import Path
from sqlalchemy.dialects.postgresql import insert

def claim_authority(store, *, room_id, expected_gateway_id, expected_epoch, new_gateway_id, event_id, now=None):
    room_id, event_id = (op_authority_native._room_id(room_id), op_authority_native._event_id(event_id))
    previous = op_authority_native._actor_id(expected_gateway_id, 'expected_gateway_id')
    gateway = op_authority_native._actor_id(new_gateway_id, 'new_gateway_id')
    epoch = op_authority_native._require_positive_int(expected_epoch, 'expected_epoch') + 1
    actor, payload = (op_authority_native._system_actor_json('authority-control'), op_authority_native._claim_payload_json(previous, gateway, epoch))
    with store.write() as conn:
        op_authority_repo.lock_store(conn, store)
        room = op_authority_repo.room(conn, store, room_id, lock=True)
        event = op_authority_repo.event(conn, store, room_id, event_id)
        replay = event is not None
        if replay:
            if op_authority_native._event_content(event) != ('authority.claimed', actor, epoch, payload):
                raise op_authority_native.EventConflictError('event_id already exists with different content')
            if room['authority_gateway_id'] != gateway or room['authority_epoch'] != epoch:
                raise op_authority_native.AuthoritySupersededError('authority claim succeeded but was later superseded')
        else:
            op_authority_native._require_authority(room, previous, expected_epoch, 'hosted room authority changed')
            event = append_on_connection(conn, store, room, event_id=event_id, kind='authority.claimed', actor_json=actor, payload_json=payload, epoch=epoch, now=clock(now), allow_control=True, authority_gateway_id=gateway, authority_epoch=epoch, revision=room['revision'] + 1)
            room = op_authority_repo.room(conn, store, room_id)
    return {**op_authority_native._room_from_row(room, idempotent=replay), 'claim_event': op_authority_native._event_from_row(event, idempotent=replay)}

def _disband_replay(conn, store, room_id, room):
    if room is None:
        timestamp = conn.scalar(select(retired.c.retired_at).where(op_authority_repo.scope(retired, store, room_id)))
        if timestamp is None:
            raise op_authority_native.RoomNotFoundError('hosted room not found')
        return {'room_id': room_id, 'disbanded_at': float(timestamp), 'idempotent': True, 'history_expired': True}
    if room['disbanded_at'] is None:
        return None
    op_authority_repo.retire(conn, store, room_id, room['disbanded_at'])
    event = op_authority_repo.event(conn, store, room_id, 'system:room-disbanded')
    return {'room_id': room_id, 'disbanded_at': float(room['disbanded_at']), 'idempotent': True, **({'event': op_authority_native._event_from_row(event, idempotent=True)} if event is not None else {})}

def disband_room(store, *, room_id, expected_gateway_id, expected_epoch, now=None):
    room_id = op_authority_native._room_id(room_id)
    gateway = op_authority_native._actor_id(expected_gateway_id, 'expected_gateway_id')
    epoch = op_authority_native._require_positive_int(expected_epoch, 'expected_epoch')
    timestamp = clock(now)
    with store.write() as conn:
        op_authority_repo.lock_store(conn, store)
        row = conn.execute(select(rooms).where(op_authority_repo.scope(rooms, store, room_id)).with_for_update()).mappings().one_or_none()
        room = op_authority_repo.decode(row) if row is not None else None
        replay = _disband_replay(conn, store, room_id, room)
        if replay is not None:
            return replay
        op_authority_native._require_authority(room, gateway, epoch, 'stale hosted room authority')
        from hermes_db.tables.rooms import owed_revokes
        pending = op_authority_repo.scope(owed_revokes, store, room_id) & (owed_revokes.c.held == 1)
        if conn.scalar(select(owed_revokes.c.room_id).where(pending, owed_revokes.c.expires_at > timestamp).limit(1)) is not None:
            raise op_authority_native.RoomHeldGrantsPendingError('Group chat grants still need revoking; retry Disband.')
        conn.execute(owed_revokes.delete().where(pending, owed_revokes.c.expires_at <= timestamp))
        event = append_on_connection(conn, store, room, event_id='system:room-disbanded', kind='room.disbanded', actor_json=op_authority_native._system_actor_json('room-control'), payload_json=op_authority_native._payload_json({'room_id': room_id}), epoch=epoch, now=timestamp, allow_control=True, disbanded_at=timestamp, revision=room['revision'] + 1)
        op_authority_repo.retire(conn, store, room_id, timestamp)
        from hermes_db.domains.rooms.postgres.ownership import forget_locked
        forget_locked(conn, store, room_id)
        prune_locked(conn, store, now=timestamp, max_gateway_event_bytes=op_authority_native.MAX_GATEWAY_EVENT_BYTES)
    return {'room_id': room_id, 'disbanded_at': timestamp, 'idempotent': False, 'event': op_authority_native._event_from_row(event)}

def probe_native_room_owner(store, *, room_id):
    with store.read() as conn:
        return owner(conn, store.scope, str(room_id)) is not None

def acquire_lease(store, *, room_id, gateway_id, authority_epoch, process_generation, ttl_seconds, clock):
    room_id = _storage_shared_1._identifier(room_id, label='room_id')
    gateway = _storage_shared_1._identifier(gateway_id, label='gateway_id')
    epoch = _storage_shared_1._bounded_int(authority_epoch, message='authority_epoch must be a positive integer', low=1)
    process = _storage_shared_1._identifier(process_generation, label='process_generation')
    now, expiry = _storage_shared_1._lease_window(ttl_seconds, clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        op_leases_repo.require_authority(conn, store, room_id, gateway, epoch)
        row = op_leases_repo.lease_row(conn, store, room_id)
        if row is None:
            row = dict(room_id=room_id, gateway_id=gateway, authority_epoch=epoch, process_generation=process, lease_generation=1, expires_at=expiry, acquired_at=now, updated_at=now, released_at=None)
            room_repo.insert_row(conn, store, leases, row)
            return _storage_shared_1._lease_from_row(row)
        same = row['gateway_id'] == gateway and row['authority_epoch'] == epoch
        live = row['released_at'] is None and row['expires_at'] > now
        if same and row['process_generation'] == process and live:
            expiry = max(row['expires_at'], expiry)
            op_leases_repo.update_lease(conn, store, room_id, expires_at=expiry, updated_at=now)
            return _storage_shared_1._lease_from_row(dict(row, expires_at=expiry))
        if same and live:
            raise _storage_shared_1.LeaseHeldError('room driver lease is held by another generation')
        fields = dict(gateway_id=gateway, authority_epoch=epoch, process_generation=process, lease_generation=row['lease_generation'] + 1, expires_at=expiry, acquired_at=now, updated_at=now, released_at=None)
        op_leases_repo.update_lease(conn, store, room_id, **fields)
        return _storage_shared_1._lease_from_row(dict(row, **fields), reclaimed=True)

def renew_lease(store, lease, *, ttl_seconds, clock):
    now, expiry = _storage_shared_1._lease_window(ttl_seconds, clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        current = op_leases_repo.active_lease(conn, store, lease, now=now)
        expiry = max(current['expires_at'], expiry)
        op_leases_repo.update_lease(conn, store, lease.room_id, expires_at=expiry, updated_at=now)
    return dataclasses.replace(lease, expires_at=expiry, reclaimed=False)

def release_lease(store, lease, *, clock):
    now = _storage_shared_1._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        op_leases_repo.require_authority(conn, store, lease.room_id, lease.gateway_id, lease.authority_epoch)
        row = op_leases_repo.lease_row(conn, store, lease.room_id)
        if not _storage_shared_1._lease_row_matches(row, lease):
            raise _storage_shared_1.StaleLeaseError('driver lease is stale')
        if row['released_at'] is not None:
            return {'lease': _storage_shared_1._lease_from_row(row), 'idempotent': True}
        if row['expires_at'] <= now:
            raise _storage_shared_1.StaleLeaseError('driver lease expired before release')
        if conn.scalar(select(tasks.c.task_id).where(room_repo.scope(tasks, store, lease.room_id), tasks.c.status == 'running').limit(1)) is not None:
            raise _storage_shared_1.InvalidTaskTransitionError('cannot release a room lease while tasks are running')
        op_leases_repo.update_lease(conn, store, lease.room_id, expires_at=now, updated_at=now, released_at=now)
    return {'lease': _storage_shared_1._lease_from_row(dict(row, expires_at=now, updated_at=now, released_at=now)), 'idempotent': False}
OWNER_PREFIX = 'gateway.hosted.owner.v1:'

def owner(conn, scope, room_id):
    return runtime.meta(conn, scope, OWNER_PREFIX + room_id)

def owners(conn, scope):
    return tuple(value[len(OWNER_PREFIX):] for value in conn.execute(select(state_meta.c.key).where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.startswith(OWNER_PREFIX, autoescape=True))).scalars())

def authorize_room(conn, store, epoch, subject, room_id, *, same_owner, create=False):
    runtime.require_epoch(conn, store.scope, epoch)
    room_repo.lock_store(conn, store)
    saved = owner(conn, store.scope, room_id)
    if saved is None and create:
        historical = any(conn.scalar(select(table.c.room_id).where(room_repo.scope(table, store, room_id))) is not None for table in (rooms, retired))
        if not historical:
            runtime.set_meta(conn, store.scope, OWNER_PREFIX + room_id, subject)
            return True
    if saved is None or not same_owner(saved, subject):
        raise RuntimeStoreError('permission_denied')
    return True

def member_authorized(conn, store, epoch, *, owner_subject, binding, member_id, profile, operation, identity, generation):
    runtime.require_epoch(conn, store.scope, epoch)
    room_repo.lock_store(conn, store)
    if owner(conn, store.scope, binding.room_id) != owner_subject:
        return False
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, binding.room_id)).with_for_update()).mappings().one_or_none()
    if row is None or row['disbanded_at'] is not None:
        return False
    room = op_coordination_native._room_from_row(room_repo.decode(row))
    if (room['authority_gateway_id'], room['authority_epoch']) != (binding.gateway_id, binding.authority_epoch):
        return False
    if not any(member.get('member_id') == member_id and member.get('profile') == profile and ((member.get('target') or {}).get('kind', 'local') == 'local') for member in room['members']):
        return False
    if identity is None:
        return True
    if identity.room_id != binding.room_id:
        return False
    try:
        row = room_runs.task(conn, store, identity, required=False)
    except _storage_shared_1.TaskConflictError:
        return False
    if row is None:
        return False
    task = _storage_shared_1._task_from_row(row)
    return task['identity'] == identity and task['execution_generation'] == generation and (task['payload']['target_profile'] == profile) and (task['payload'].get('target_member_id', profile) == member_id) and (task['status'] in ({'running'} if operation in {'submit', 'execute'} else {'running', 'stopping'}))

def _key(db, key):
    return (state_meta.c.store_id == db.scope.require_store_id()) & (state_meta.c.key == key)

def recorded_homes(db, room_id, member_id):
    with db._read() as conn:
        value = conn.scalar(select(state_meta.c.value).where(_key(db, _storage_shared_1._key(room_id, member_id))))
    return [Path(home) for home in json.loads(value)] if value is not None else []

def record_member_home(db, room_id, member_id, home):
    home, key = (str(home), _storage_shared_1._key(room_id, member_id))
    if Path(home) in recorded_homes(db, room_id, member_id):
        return
    with db._write() as conn:
        room_repo.lock_store(conn, db)
        value = conn.scalar(select(state_meta.c.value).where(_key(db, key)))
        homes = json.loads(value) if value is not None else []
        if home not in homes:
            stmt = insert(state_meta).values(store_id=db.scope.require_store_id(), key=key, value=json.dumps([*homes, home]))
            conn.execute(stmt.on_conflict_do_update(index_elements=list(state_meta.primary_key.columns), set_={'value': stmt.excluded.value}))

def _attempts(conn, db, room_id, member_id, statuses):
    rows = conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == db.scope.require_store_id(), state_meta.c.key.startswith(_storage_shared_1._attempt_prefix(room_id, member_id), autoescape=True))).all()
    ids = {json.loads(key[len(_storage_shared_1._HOMES):])[2] for key, _ in rows}
    current = {row['task_id']: row for row in conn.execute(select(tasks.c.task_id, tasks.c.status, tasks.c.execution_generation).where(room_repo.scope(tasks, db, room_id), tasks.c.task_id.in_(ids))).mappings()}
    found = {}
    for key, home in rows:
        task_id, generation = json.loads(key[len(_storage_shared_1._HOMES):])[2:]
        row = current.get(task_id)
        found[key] = (home, bool(row and row['status'] in statuses and (row['execution_generation'] == generation)))
    return found

def record_attempt_home(db, room_id, member_id, task_id, generation, home):
    key = _storage_shared_1._HOMES + json.dumps([room_id, member_id, task_id, int(generation)], separators=(',', ':'))
    with db._write() as conn:
        room_repo.lock_store(conn, db)
        for old, (_, live) in _attempts(conn, db, room_id, member_id, _storage_shared_1._LIVE_ATTEMPT).items():
            if not live and old != key:
                conn.execute(delete(state_meta).where(_key(db, old)))
        conn.execute(insert(state_meta).values(store_id=db.scope.require_store_id(), key=key, value=str(home)).on_conflict_do_nothing())

def stopping_attempt_home(db, room_id, member_id, task):
    if task.get('status') not in _storage_shared_1._STOPPING:
        return None
    key = _storage_shared_1._HOMES + json.dumps([room_id, member_id, task['identity'].task_id, int(task['execution_generation'])], separators=(',', ':'))
    with db._read() as conn:
        value = conn.scalar(select(state_meta.c.value).where(_key(db, key)))
    return Path(value) if value is not None else None

def stopping_attempt_homes(db, room_id, member_id):
    with db._read() as conn:
        return {home for home, live in _attempts(conn, db, room_id, member_id, _storage_shared_1._STOPPING).values() if live}

def forget_locked(conn, store, room_id):
    prefix = _storage_shared_1._HOMES + json.dumps([room_id], separators=(',', ':'))[:-1] + ','
    conn.execute(delete(state_meta).where(state_meta.c.store_id == store.scope.require_store_id(), state_meta.c.key.startswith(prefix, autoescape=True)))
