"""Scoped Cron attempt/incident records, short fenced writes and original post-commit observers."""
from contextlib import contextmanager
from datetime import datetime, UTC
import math
from sqlalchemy import and_, delete, select, update, tuple_, func
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.cron import cron_executions as executions, cron_incidents as incidents, cron_locks as locks
from hermes_db.core.values import decode_text, encode_text
import os
_BYTES = {'id', 'job_id', 'source', 'process_id', 'error', 'delivery_outcome', 'failure_type', 'output_file'}
_PROJECTIONS = {'claimed_order', 'finished_order', 'last_seen_order'}

def _instant_order(value):
    if value is None:
        return None
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return math.floor(instant.timestamp() * 1000 + 0.5)

def _scoped(table, scope):
    return table.c.store_id == scope.require_store_id()

def _key(table, scope, record_id):
    return and_(_scoped(table, scope), table.c.id == encode_text(str(record_id)))

def _encode(values):
    result = {name: encode_text(value) if name in _BYTES else value for name, value in values.items()}
    for source, projection in (('claimed_at', 'claimed_order'), ('finished_at', 'finished_order'), ('last_seen_at', 'last_seen_order')):
        if source in result:
            result[projection] = _instant_order(result[source])
    return result

def _decode(row):
    if row is None:
        return None
    return {name: decode_text(value) if name in _BYTES else value for name, value in row.items() if name != 'store_id' and name not in _PROJECTIONS}

def _fetch(conn, table, scope, record_id):
    return _decode(conn.execute(select(table).where(_key(table, scope, record_id))).mappings().one_or_none())

def _rows(conn, query):
    return [_decode(row) for row in conn.execute(query).mappings()]

@contextmanager
def _write(resource):
    with resource.write() as conn:
        conn.execute(insert(locks).values(store_id=resource.scope.require_store_id()).on_conflict_do_nothing())
        conn.execute(select(locks.c.store_id).where(_scoped(locks, resource.scope)).with_for_update()).one()
        yield conn

def _update_execution(conn, scope, execution_id, condition, values):
    return conn.execute(update(executions).where(_key(executions, scope, execution_id), condition).values(**_encode(values))).rowcount == 1

def _execution_order():
    return (executions.c.claimed_order.desc(), executions.c.claimed_at.desc(), executions.c.id.desc())

def _prune(conn, scope, limit):
    from hermes_db.domains.cron.rules import TERMINAL_EXECUTION_STATES as _TERMINAL_STATES
    retained = select(executions.c.id).where(_scoped(executions, scope), executions.c.status.in_(_TERMINAL_STATES))
    retained = retained.order_by(executions.c.finished_order.desc().nulls_last(), executions.c.finished_at.desc(), *_execution_order()).limit(max(0, int(limit)))
    conn.execute(delete(executions).where(_scoped(executions, scope), executions.c.status.in_(_TERMINAL_STATES), executions.c.id.not_in(retained)))

def _snapshot_condition(row):
    return and_(*(getattr(executions.c, name).is_not_distinct_from(_encode({name: row[name]})[name]) for name in ('status', 'process_id', 'pid', 'handoff_pending', 'handoff_started_at', 'claimed_at', 'progress_at')))

def _owned(resource):
    ex = resource.executions
    return and_(executions.c.process_id == encode_text(ex.process_id), executions.c.pid == os.getpid())

def _active():
    return executions.c.status.in_(('claimed', 'running'))

def _update(resource, execution_id, condition, values, *, prune=False, emit=True, finish=False):
    ex = resource.executions
    with _write(resource) as conn:
        if not _update_execution(conn, resource.scope, execution_id, condition, values):
            return (False, None)
        if prune:
            _prune(conn, resource.scope, ex.max_terminal)
        record = _fetch(conn, executions, resource.scope, execution_id)
    if emit:
        ex.emit_state(record, delivery_outcome=values.get('delivery_outcome'))
    if finish:
        ex.record_finish(record, values.get('delivery_outcome'))
    return (True, record)

def _insert(resource, job_id, source, *, status='claimed', error=None, scheduled_instant=None):
    ex = resource.executions
    from cron.occurrences import scheduled_instant as canonical
    now, execution_id, pid = (ex.now().isoformat(), ex.uuid.uuid4().hex, os.getpid())
    values = {'id': execution_id, 'job_id': str(job_id), 'source': str(source), 'process_id': ex.process_id, 'pid': pid, 'process_started_at': ex.process_start_time(pid), 'status': status, 'claimed_at': now, 'error': error, 'scheduled_instant': canonical(scheduled_instant)}
    if status == 'missed':
        values['finished_at'] = now
    with _write(resource) as conn:
        conn.execute(executions.insert().values(store_id=resource.scope.require_store_id(), **_encode(values)))
        if status == 'missed':
            _prune(conn, resource.scope, ex.max_terminal)
        record = _fetch(conn, executions, resource.scope, execution_id)
    ex.emit_state(record)
    return record

def create_execution(resource, job_id, *, source, scheduled_instant=None):
    return _insert(resource, job_id, source, scheduled_instant=scheduled_instant)

def record_missed_occurrences(resource, job_id, *, count, first_instant, detail):
    if count < 1:
        return None
    return _insert(resource, job_id, 'scheduler', status='missed', error=f'missed ×{count} ({detail})', scheduled_instant=first_instant)

def touch_execution_progress(resource, execution_id):
    ex = resource.executions
    return _update(resource, execution_id, and_(_owned(resource), _active()), {'progress_at': ex.now().isoformat()}, emit=False)[0]

def set_execution_occurrence(resource, execution_id, instant):
    from cron.occurrences import scheduled_instant
    changed, _record = _update(resource, execution_id, and_(_owned(resource), executions.c.status == 'claimed', executions.c.handoff_pending == 0), {'scheduled_instant': scheduled_instant(instant)}, emit=False)
    if not changed:
        raise RuntimeError('Cron occurrence could not be bound before dispatch')

def mark_execution_handoff_pending(resource, execution_id):
    ex = resource.executions
    return _update(resource, execution_id, and_(_owned(resource), executions.c.status == 'claimed'), {'handoff_pending': 1, 'handoff_started_at': ex.time.time()})[1]

def adopt_claimed_execution(resource, execution_id):
    ex = resource.executions
    pid = os.getpid()
    return _update(resource, execution_id, and_(executions.c.status == 'claimed', executions.c.handoff_pending == 1), {'process_id': ex.process_id, 'pid': pid, 'process_started_at': ex.process_start_time(pid), 'status': 'running', 'started_at': ex.now().isoformat(), 'handoff_pending': 0, 'handoff_started_at': None})[1]

def mark_execution_running(resource, execution_id):
    ex = resource.executions
    return _update(resource, execution_id, and_(_owned(resource), executions.c.status == 'claimed', executions.c.handoff_pending == 0), {'status': 'running', 'started_at': ex.now().isoformat(), 'handoff_pending': 0, 'handoff_started_at': None})[1]

def finish_execution(resource, execution_id, *, success, error=None, delivery_outcome=None, cancelled=False):
    ex = resource.executions
    return _update(resource, execution_id, and_(_owned(resource), _active()), {'status': 'cancelled' if cancelled else 'completed' if success else 'failed', 'finished_at': ex.now().isoformat(), 'error': None if success else str(error) if error else 'unknown failure', 'handoff_pending': 0, 'handoff_started_at': None, 'delivery_outcome': delivery_outcome}, prune=True, finish=True)[1]

def give_up_execution(resource, execution_id, *, reason):
    ex = resource.executions
    return _update(resource, str(execution_id), and_(_owned(resource), _active()), {'status': 'unknown', 'finished_at': ex.now().isoformat(), 'error': reason, 'handoff_pending': 0, 'handoff_started_at': None}, prune=True)[0]

def settle_delivery_outcome(resource, execution_id, outcome):
    return _update(resource, execution_id, and_(executions.c.delivery_outcome == encode_text('queued'), executions.c.status.in_(('completed', 'failed', 'unknown'))), {'delivery_outcome': outcome}, emit=False)[0]

def get_execution(resource, execution_id):
    with resource.read() as conn:
        return _fetch(conn, executions, resource.scope, str(execution_id))

def list_executions(resource, *, job_id=None, limit=50, before_claimed_at=None):
    query = select(executions).where(_scoped(executions, resource.scope))
    if job_id is not None:
        query = query.where(executions.c.job_id == encode_text(str(job_id)))
    if before_claimed_at is not None:
        query = query.where(tuple_(executions.c.claimed_order, executions.c.claimed_at) < tuple_(_instant_order(str(before_claimed_at)), str(before_claimed_at)))
    with resource.read() as conn:
        return _rows(conn, query.order_by(*_execution_order()).limit(max(1, min(int(limit), 500))))

def live_inflight_execution(resource, job_id):
    ex = resource.executions
    with resource.read() as conn:
        query = select(executions).where(_scoped(executions, resource.scope), executions.c.job_id == encode_text(job_id), executions.c.status != 'missed')
        rows = _rows(conn, query.order_by(*_execution_order()).limit(1))
    record = rows[0] if rows else None
    return record if record and record['status'] in ('claimed', 'running') and ex.owner_is_live(int(record['pid']), record['process_started_at']) else None

def _jobs(resource, job_ids, *, live):
    ex = resource.executions
    clean = [str(job_id) for job_id in dict.fromkeys(job_ids) if job_id]
    if not clean:
        return {}
    query = select(executions).where(_scoped(executions, resource.scope), executions.c.job_id.in_([encode_text(job_id) for job_id in clean]))
    if live:
        query = query.where(_active())
    with resource.read() as conn:
        rows = _rows(conn, query.order_by(*_execution_order()))
    result = {}
    for row in rows:
        if row['job_id'] not in result and (not live or ex.row_owner_live(row)):
            result[row['job_id']] = row
    return result

def live_executions(resource, job_ids):
    return _jobs(resource, job_ids, live=True)

def latest_executions(resource, job_ids):
    return _jobs(resource, job_ids, live=False)

def _recoverable(row, job_id):
    return row is not None and row['job_id'] == str(job_id) and (row['status'] in ('claimed', 'running', 'unknown'))

def execution_owner_live(resource, execution_id, job_id):
    ex = resource.executions
    row = get_execution(resource, execution_id)
    return _recoverable(row, job_id) and ex.row_owner_live(row)

def recover_receipted_execution(resource, execution_id, job_id, *, success, error=None, delivery_outcome=None):
    ex = resource.executions
    row = get_execution(resource, execution_id)
    if not _recoverable(row, job_id) or ex.row_owner_live(row):
        return None
    return _update(resource, execution_id, _snapshot_condition(row), {'status': 'completed' if success else 'failed', 'finished_at': ex.now().isoformat(), 'error': None if success else str(error) if error else 'unknown failure', 'handoff_pending': 0, 'handoff_started_at': None, 'delivery_outcome': delivery_outcome}, prune=True, finish=True)[1]

def _handoff_grace(resource, row):
    ex = resource.executions
    return row['handoff_pending'] and row['handoff_started_at'] is not None and (ex.time.time() - float(row['handoff_started_at']) < ex.handoff_grace_seconds)

def terminalize_dead_owner(resource, execution_id, *, reason):
    ex = resource.executions
    row = get_execution(resource, execution_id)
    if row is None or row['status'] not in ('claimed', 'running') or row['process_id'] == ex.process_id:
        return False
    if ex.owner_is_live(int(row['pid']), row['process_started_at']) or _handoff_grace(resource, row):
        return False
    return _update(resource, execution_id, _snapshot_condition(row), {'status': 'unknown', 'finished_at': ex.now().isoformat(), 'error': reason, 'handoff_pending': 0, 'handoff_started_at': None}, prune=True)[0]

def recover_interrupted_executions(resource):
    ex = resource.executions
    with resource.read() as conn:
        rows = _rows(conn, select(executions).where(_scoped(executions, resource.scope), _active()))
    changed, stale_after, resolved = (0, None, False)
    for row in rows:
        if row['process_id'] == ex.process_id:
            continue
        reason = ex.owner_gone_reason
        if ex.owner_is_live(int(row['pid']), row['process_started_at']):
            if not resolved:
                stale_after, resolved = (ex.live_owner_stale_after_seconds(), True)
            if stale_after is None or ex.stale_age_seconds(row['claimed_at'], row['progress_at']) <= stale_after:
                continue
            reason = ex.owner_wedged_reason
        if _handoff_grace(resource, row):
            continue
        changed += _update(resource, row['id'], _snapshot_condition(row), {'status': 'unknown', 'finished_at': ex.now().isoformat(), 'error': reason, 'handoff_pending': 0, 'handoff_started_at': None}, prune=True)[0]
    return changed

def completed_occurrence_rows(resource, job_id, instant):
    with resource.read() as conn:
        return _rows(conn, select(executions).where(_scoped(executions, resource.scope), executions.c.job_id == encode_text(str(job_id)), executions.c.scheduled_instant == instant, executions.c.status == 'completed'))

def upsert_incident(resource, job_id, error, *, job_name=None, failure_type=None, output_file=None):
    inc = resource.incidents
    job_id = str(job_id or '')
    sig = inc.error_signature(job_id, error)
    incident_id, now = (inc.incident_id(job_id, sig), inc.now().isoformat())
    values = {'last_seen_at': now, 'error': inc.redact_error(error), 'output_file': str(output_file) if output_file is not None else None}
    with _write(resource) as conn:
        row = _fetch(conn, incidents, resource.scope, incident_id)
        if row is not None:
            reopen = row['state'] == 'resolved'
            if reopen:
                values.update(state='detected', alerted_at=None, closed_at=None)
            conn.execute(update(incidents).where(_key(incidents, resource.scope, incident_id)).values(**_encode(values)))
            return (incident_id, reopen)
        values.update(id=incident_id, job_id=job_id, error_sig=sig, state='detected', first_seen_at=now, failure_type=failure_type or inc.classify_failure_type(error))
        conn.execute(incidents.insert().values(store_id=resource.scope.require_store_id(), **_encode(values)))
        return (incident_id, True)

def set_incident_state(resource, incident_id, state):
    inc = resource.incidents
    if state not in inc.states:
        return False
    now = inc.now().isoformat()
    with _write(resource) as conn:
        row = _fetch(conn, incidents, resource.scope, incident_id)
        if row is None or row['state'] == 'closed':
            return False
        values = {'state': state}
        if state == 'alerted':
            values['alerted_at'] = now
        elif row['state'] == state:
            return False
        elif state == 'closed':
            values.update(closed_at=now, acked_at=now)
        conn.execute(update(incidents).where(_key(incidents, resource.scope, incident_id)).values(**values))
        return True

def close_incidents_for_recovered_job(resource, job_id):
    inc = resource.incidents
    now = inc.now().isoformat()
    with _write(resource) as conn:
        return conn.execute(update(incidents).where(_scoped(incidents, resource.scope), incidents.c.job_id == encode_text(str(job_id or '')), incidents.c.state.in_(('detected', 'alerted'))).values(state='resolved', closed_at=now)).rowcount

def list_incidents(resource, state=None):
    inc = resource.incidents
    if state is not None and state not in inc.states:
        return []
    query = select(incidents).where(_scoped(incidents, resource.scope))
    if state is not None:
        query = query.where(incidents.c.state == state)
    with resource.read() as conn:
        return _rows(conn, query.order_by(incidents.c.last_seen_order.desc(), incidents.c.last_seen_at.desc(), incidents.c.id.desc()))

def get_incident(resource, incident_id):
    with resource.read() as conn:
        return _fetch(conn, incidents, resource.scope, incident_id)

def count_incidents(resource, state=None):
    inc = resource.incidents
    if state is not None and state not in inc.states:
        return 0
    query = select(func.count()).select_from(incidents).where(_scoped(incidents, resource.scope))
    if state is not None:
        query = query.where(incidents.c.state == state)
    with resource.read() as conn:
        return conn.scalar(query)
