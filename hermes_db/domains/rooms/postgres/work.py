"""Room work workflow; original connection, fence and off-connection effect boundaries are preserved."""
import json
import logging
from sqlalchemy.exc import DBAPIError
from sqlalchemy import select, update, or_, cast, func, LargeBinary, Text
from gateway import hosted_room_work_records as native, hosted_room_work_lineage as lineage, hosted_room_driver as driver, hosted_room_authority_history as history, hosted_room_work_storage as storage
from hermes_db.domains.rooms.postgres import repository as room_repo
from hermes_db.tables.room_work import source, pending, publications
from hermes_db.tables.rooms import rooms, events, remote_runs
from hermes_db.tables.room_runs import tasks
from hermes_db.core.values import encode_text

def _record(content, revision):
    return {**content, 'revision': revision, 'digest': native.digest(content)}

def capture_locked(conn, store, *, room_id, local_gateway_id, through_seq=None):
    room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
    if room['authority_gateway_id'] != local_gateway_id or room['disbanded_at'] is not None:
        raise native.WorkRecordError('work record source is unavailable')
    if through_seq is not None and room['next_seq'] - 1 > through_seq:
        raise native.WorkRecordPrefixError('history delivery must precede work records')
    content, spans = _snapshot_content(conn, store, room)
    previous = read(conn, store, source, record_key(source, store, content))
    previous_record = validate_locked(conn, store, source, previous) if previous is not None else None
    revision = previous_record['revision'] + 1 if previous_record else 1
    record = _record(content, revision)
    if len(native.encode(record).encode('utf-8')) > native.MAX_BYTES:
        content.update(tasks=[], receipts=[], availability='unavailable', reason='bounds_exceeded')
        record = _record(content, revision)
    try:
        native.validate(record)
        native._validate_roster(record, json.loads(room['members_json']))
        if spans is not None:
            lineage.validate_provenance(record, spans)
    except native.WorkRecordError:
        if content['reason'] is not None:
            raise
        content.update(tasks=[], receipts=[], availability='unavailable', reason='unsupported_task')
        record = native.validate(_record(content, revision))
    if previous_record is not None and previous_record['digest'] == record['digest']:
        return previous_record
    save(conn, store, source, record)
    return record

def capture(store, *, room_id, local_gateway_id, through_seq=None):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        try:
            return capture_locked(conn, store, room_id=room_id, local_gateway_id=local_gateway_id, through_seq=through_seq)
        except native.InvalidStoredWorkRecord:
            pass
    raise native.InvalidStoredWorkRecord('stored work evidence is invalid')

def capture_transition_locked(conn, store, room_id):
    from gateway.hosted_rooms_common import IDENTIFIER_RE
    if not isinstance(room_id, str) or not IDENTIFIER_RE.fullmatch(room_id):
        return
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, room_id))).mappings().one_or_none()
    if row is None or row['disbanded_at'] is not None:
        return
    room = room_repo.decode(row)
    savepoint = conn.begin_nested()
    try:
        capture_locked(conn, store, room_id=room_id, local_gateway_id=room['authority_gateway_id'])
    except native.InvalidStoredWorkRecord:
        savepoint.commit()
        logging.getLogger(__name__).warning('Hosted work evidence invalid for room %s', room_id)
    except (native.WorkRecordError, DBAPIError):
        savepoint.rollback()
        logging.getLogger(__name__).warning('Hosted work evidence unavailable for room %s', room_id, exc_info=True)
    else:
        savepoint.commit()

def prepare_locked(conn, store, *, room_id, target_install_id, route_generation, local_gateway_id, through_seq):
    room = room_repo.room(conn, store, room_id, include_disbanded=True, lock=True)
    if room['authority_gateway_id'] != local_gateway_id:
        raise native.WorkRecordError('work record source is unavailable')
    scope = dict(room_id=room_id, authority=dict(gateway_id=room['authority_gateway_id'], epoch=room['authority_epoch']))
    key = record_key(pending, store, scope, target_install_id)
    old = read(conn, store, pending, key)
    previous = validate_locked(conn, store, pending, old) if old is not None else None
    if old is not None and old['disposition'] != 'current':
        raise native.WorkRecordError('pending work record is not current')
    if old is not None and old['status'] != 'acked':
        if old['route_generation'] == route_generation and old['status'] in native.BLOCKED_DELIVERY_STATUSES:
            return None
        record = previous
        if record['home_install_id'] != local_gateway_id or record['authority'] != scope['authority'] or record['roster_sha256'] != native.roster_digest(json.loads(room['members_json'])):
            raise native.WorkRecordError('pending work record source changed')
        conn.execute(update(pending).where(key, pending.c.disposition == 'current').values(route_generation=route_generation, status='pending'))
    else:
        record = capture_locked(conn, store, room_id=room_id, local_gateway_id=local_gateway_id)
        if old is not None and (old['revision'], old['digest']) == (record['revision'], record['digest']):
            return None
        save(conn, store, pending, record, target_install_id=target_install_id, route_generation=route_generation)
    return record if record['history']['seq'] <= through_seq else None

def status_locked(conn, store, *, room_id, target_install_id, route_generation, record, status):
    key = record_key(pending, store, record, target_install_id)
    row = read(conn, store, pending, key)
    if row is None or row['room_id'] != room_id or row['disposition'] != 'current':
        return False
    try:
        if validate_locked(conn, store, pending, row) != record:
            return False
    except native.InvalidStoredWorkRecord:
        return False
    return conn.execute(update(pending).where(key, pending.c.route_generation == route_generation, pending.c.revision == record['revision'], pending.c.digest == record['digest'], pending.c.disposition == 'current').values(status=status)).rowcount == 1

def _write(store, operation, **params):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        try:
            return operation(conn, store, **params)
        except native.InvalidStoredWorkRecord:
            pass
    raise native.InvalidStoredWorkRecord('stored work evidence is invalid')

def prepare_delivery(store, **params):
    return _write(store, prepare_locked, **params)

def delivery_status(store, **params):
    return _write(store, status_locked, **params)

def acknowledge(store, *, ack, record, **params):
    if native.encode(ack) != native.encode(native.acknowledgement(record)):
        return False
    return delivery_status(store, record=record, status='acked', **params)

def history_anchor(conn, store, room_id, seq):
    if seq == 0:
        return native.digest([])
    row = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq == seq)).mappings().one_or_none()
    if row is None:
        raise native.WorkRecordPrefixError('work record history prefix is unavailable')
    row = room_repo.decode(row)
    return native.digest([row['seq'], row['event_id'], row['kind'], json.loads(row['actor_json']), row['authority_epoch'], json.loads(row['payload_json']), float(row['created_at'])])

def source_prefix(conn, store, room_id, authority, seq):
    transfers = [room_repo.decode(row) for row in conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.kind.in_([encode_text(kind) for kind in history.TRANSFER_KINDS])).order_by(events.c.seq).limit(history.MAX_AUTHORITY_SPANS)).mappings()]
    lineage = history.history_from_rows(transfers, gateway_id=authority['gateway_id'], epoch=authority['epoch'])
    if lineage is None:
        raise native.WorkRecordPrefixError('successor work evidence has no verified lineage')
    spans = history.validate_history(lineage, gateway_id=authority['gateway_id'], epoch=authority['epoch'])
    count = 0
    for row in conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq <= seq).order_by(events.c.seq)).mappings():
        count += 1
        event = room_repo.decode(row)
        span, actor = (history.at_sequence(spans, count), json.loads(event['actor_json']))
        boundary = span.epoch > 1 and count == span.from_seq
        if event['seq'] != count or event['authority_epoch'] != span.epoch or (actor.get('kind') == 'gateway' and actor.get('id') != span.gateway_id) or ((event['kind'] in history.TRANSFER_KINDS) != boundary):
            raise native.WorkRecordPrefixError('work record history prefix is not verified')
    if count != seq:
        raise native.WorkRecordPrefixError('work record history prefix is unavailable')
    return (spans, native.digest(lineage))

def _task_values(rows):
    result = []
    for row in rows:
        row = room_repo.decode(row)
        try:
            payload, encoded, digest = driver._task_payload(json.loads(row['payload_json']))
        except (ValueError, driver.DriverStateError):
            return ([], 'unsupported_task')
        if digest != row['payload_digest'] or encoded != row['payload_json'] or payload['source_event_seq'] != row['source_event_seq']:
            return ([], 'unsupported_task')
        result.append({**{key: row[key] for key in native._TASK_FIELDS - {'payload_sha256', 'phase', 'member_id', 'profile'}}, 'payload_sha256': digest, 'phase': row['status'], 'profile': payload['target_profile'], 'member_id': payload.get('target_member_id', payload['target_profile'])})
    return (result, None)

def capture_tasks(conn, store, room_id):
    rows = conn.execute(select(tasks).where(room_repo.scope(tasks, store, room_id), or_(tasks.c.status.not_in(driver.TERMINAL_STATUSES), unpublished(tasks, store))).order_by(tasks.c.task_id).limit(native.MAX_TASKS + 1)).mappings().all()
    receipts = [room_repo.record(row) for row in conn.execute(select(*[remote_runs.c[key] for key in sorted(native._RECEIPT_FIELDS)]).where(room_repo.scope(remote_runs, store, room_id), unpublished(remote_runs, store)).order_by(remote_runs.c.task_id, remote_runs.c.execution_generation, remote_runs.c.member_id).limit(native.MAX_RECEIPTS + 1)).mappings()]
    if len(rows) > native.MAX_TASKS or len(receipts) > native.MAX_RECEIPTS:
        return ([], [], 'bounds_exceeded')
    values, reason = _task_values(rows)
    return ([], [], reason) if reason else (values, receipts, None)

def _snapshot_content(conn, store, room):
    room_id, seq = (room['room_id'], room['next_seq'] - 1)
    values, receipts, reason = capture_tasks(conn, store, room_id)
    stop = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.kind == encode_text('room.stop_requested')).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    stop = room_repo.decode(stop) if stop is not None else None
    result = dict(version=1 if room['authority_epoch'] == 1 else 2, room_id=room_id, home_install_id=room['authority_gateway_id'], authority=dict(gateway_id=room['authority_gateway_id'], epoch=room['authority_epoch']), roster_sha256=native.roster_digest(json.loads(room['members_json'])), history=dict(seq=seq, event_sha256=history_anchor(conn, store, room_id, seq)), availability='unavailable' if reason else 'available', reason=reason, tasks=values, receipts=receipts, limitations=native.LIMITATIONS, stop=dict(closing=False, revocation_complete=False, seq=stop['seq'] if stop else 0, cancel_id=json.loads(stop['payload_json']).get('cancel_id') if stop else None))
    spans = None
    if result['version'] == 2:
        spans, result['lineage_sha256'] = source_prefix(conn, store, room_id, result['authority'], seq)
        result['incompleteness'] = ['prior_authority_work_unknown']
    return (result, spans)

def unpublished(table, store):

    def comparable(column, target):
        return func.convert_to(column, 'UTF8') if isinstance(target.type, LargeBinary) and (not isinstance(column.type, LargeBinary)) else column
    return ~select(publications.c.task_id).where(room_repo.scope(publications, store), comparable(publications.c.room_id, table.c.room_id) == table.c.room_id, comparable(publications.c.task_id, table.c.task_id) == comparable(table.c.task_id, publications.c.task_id), publications.c.kind.in_(('turn.settled', 'turn.failed', 'turn.cancelled'))).exists()

def record_key(table, store, record, target=None):
    fields = dict(room_id=record['room_id'], producer_gateway_id=record['authority']['gateway_id'], producer_epoch=record['authority']['epoch'])
    if target is not None:
        fields['target_install_id'] = target
    return room_repo.key(table, store, fields)

def read(conn, store, table, condition):
    row = conn.execute(select(table).where(room_repo.scope(table, store), condition).with_for_update()).mappings().one_or_none()
    return room_repo.record(row) if row is not None else None

def validate_locked(conn, store, table, row):
    try:
        return storage.validate_stored(row)
    except native.InvalidStoredWorkRecord:
        if row['disposition'] == 'current':
            conn.execute(update(table).where(room_repo.key(table, store, row)).values(disposition='invalid'))
        raise

def _size(table):
    fields = storage.retained_fields(table.name)
    return 20 + sum(func.coalesce(func.octet_length(table.c[field] if field == 'record_json' else func.convert_to(cast(table.c[field], Text), 'UTF8')), 0) for field in fields)

def _budget(conn, store, table, row, previous):
    total = count = 0
    for retained in (source, pending):
        size, rows = conn.execute(select(func.coalesce(func.sum(_size(retained)), 0), func.count()).select_from(retained).where(room_repo.scope(retained, store))).one()
        total += int(size)
        count += rows

    def size_of(value):
        return 20 + sum(len(str(value[field]).encode('utf-8')) for field in storage.retained_fields(table.name) if value.get(field) is not None)
    old_size = size_of(previous) if previous else 0
    if total - old_size + size_of(row) > native.MAX_STORE_BYTES or count - bool(previous) + 1 > native.MAX_STORE_ROWS:
        raise native.WorkRecordCapacityError('work record storage is full')

def save(conn, store, table, record, *, target_install_id=None, route_generation=None):
    row = dict(room_id=record['room_id'], producer_gateway_id=record['authority']['gateway_id'], producer_epoch=record['authority']['epoch'], revision=record['revision'], digest=record['digest'], record_json=native.encode(record), disposition='current')
    if target_install_id is not None:
        row.update(target_install_id=target_install_id, route_generation=route_generation, status='pending')
    condition = record_key(table, store, record, target_install_id)
    previous = read(conn, store, table, condition)
    if previous is not None and previous['disposition'] != 'current':
        raise native.WorkRecordError('historical work record is immutable')
    _budget(conn, store, table, row, previous)
    if previous is None:
        room_repo.insert_row(conn, store, table, row)
    else:
        conn.execute(update(table).where(condition).values(**room_repo.values(table, row)))
