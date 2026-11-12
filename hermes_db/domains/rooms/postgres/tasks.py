"""Room tasks workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms import driver_rules as _storage_shared_1
import dataclasses
from sqlalchemy import select, delete
from hermes_db.domains.rooms import driver_rules as native
from hermes_db.domains.rooms.postgres import repository as room_repo, repository as repo, work as room_work
from hermes_db.tables.room_runs import tasks
from hermes_db.domains.rooms.postgres.work import capture_transition_locked

def change(store, identity, *, now, fields, lease=None, lease_first=True, replay=None, guard=None):
    """All writers serialize on the scoped room lock before checking a task fence."""
    if lease is not None:
        _storage_shared_1._check_same_room(lease, identity)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        if lease is not None and lease_first:
            repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, identity)
        if replay is not None and (result := replay(row)) is not None:
            return result
        if lease is not None and (not lease_first):
            repo.active_lease(conn, store, lease, now=now)
        if guard is not None:
            guard(row)
        repo.update_task(conn, store, identity, **fields)
        capture_transition_locked(conn, store, identity.room_id)
        return _storage_shared_1._task_from_row(repo.task(conn, store, identity))

def admit_task(store, identity, *, payload, clock):
    normalized, encoded, digest = _storage_shared_1._task_payload(payload)
    now = _storage_shared_1._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_room(conn, store, identity.room_id)
        row = repo.task(conn, store, identity, required=False)
        if row is not None:
            if row['payload_digest'] != digest or row['payload_json'] != encoded:
                raise _storage_shared_1.TaskConflictError('task_id is already bound to a different payload')
            return _storage_shared_1._task_from_row(row, idempotent=True)
        bound = conn.scalar(select(tasks.c.task_id).where(room_repo.scope(tasks, store, identity.room_id), tasks.c.thread_id == identity.thread_id, tasks.c.turn_id == identity.turn_id))
        if bound is not None:
            raise _storage_shared_1.TaskConflictError('thread_id and turn_id are already bound to a task')
        room_repo.insert_row(conn, store, tasks, dict(dataclasses.asdict(identity), source_event_seq=normalized['source_event_seq'], payload_json=encoded, payload_digest=digest, status='queued', execution_generation=0, cancel_generation=0, created_at=now, updated_at=now))
        capture_transition_locked(conn, store, identity.room_id)
        return _storage_shared_1._task_from_row(repo.task(conn, store, identity))

def start_task(store, identity, lease, *, expected_cancel_generation, clock):
    _storage_shared_1._check_same_room(lease, identity)
    _storage_shared_1._cancel_generation(expected_cancel_generation)
    now = _storage_shared_1._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, identity)
        _storage_shared_1._require_cancel_generation(row, expected_cancel_generation)
        if row['status'] != 'queued':
            raise _storage_shared_1.InvalidTaskTransitionError(f"cannot start task in state '{row['status']}'")
        ordered = repo.task_rows(conn, store, identity.room_id)
        if any(task['status'] in {'running', 'indeterminate', 'stopping'} for task in ordered):
            raise _storage_shared_1.InvalidTaskTransitionError('room recovery must resolve the prior task before starting new work')
        queued = next((task for task in ordered if task['status'] == 'queued'), None)
        if queued is None or queued['task_id'] != identity.task_id:
            raise _storage_shared_1.InvalidTaskTransitionError('task is not next in the hosted room event order')
        generation = int(row['execution_generation']) + 1
        repo.update_task(conn, store, identity, status='running', execution_generation=generation, run_gateway_id=lease.gateway_id, run_process_generation=lease.process_generation, run_lease_generation=lease.lease_generation, started_at=now, updated_at=now)
        capture_transition_locked(conn, store, identity.room_id)
        return _storage_shared_1.TaskAttempt(identity, lease, generation, expected_cancel_generation)

def mark_attempt_indeterminate(store, attempt, lease, *, clock):
    _storage_shared_1._check_same_room(lease, attempt.identity)
    now = _storage_shared_1._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, attempt.identity)
        if not _storage_shared_1._generations_match(row, 'running', attempt.execution_generation, attempt.cancel_generation):
            return
        repo.update_task(conn, store, attempt.identity, status='indeterminate', indeterminate_at=now, updated_at=now)
        capture_transition_locked(conn, store, lease.room_id)

def recover_room(store, lease, *, clock):
    now = _storage_shared_1._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        for row in repo.task_rows(conn, store, lease.room_id, 'running'):
            if (row['run_gateway_id'], row['run_process_generation'], row['run_lease_generation']) != _storage_shared_1._run_fence(lease):
                repo.update_task(conn, store, _storage_shared_1._task_identity_from_row(row), status='indeterminate', indeterminate_at=now, updated_at=now)
        capture_transition_locked(conn, store, lease.room_id)
        return {status: [_storage_shared_1._task_identity_from_row(row) for row in repo.task_rows(conn, store, lease.room_id, status)] for status in ('queued', 'indeterminate')}

def get_task(store, identity):
    with store.read() as conn:
        return _storage_shared_1._task_from_row(repo.task(conn, store, identity, lock=False))

def list_tasks(store, *, room_id, status=None):
    room_id = _storage_shared_1._identifier(room_id, label='room_id')
    if status is not None and status not in _storage_shared_1.TASK_STATUSES:
        raise _storage_shared_1.DriverValidationError('invalid task status')
    with store.read() as conn:
        return [_storage_shared_1._task_from_row(row) for row in repo.task_rows(conn, store, room_id, status)]

def get_task_for_turn(store, identity):
    with store.read() as conn:
        row = conn.execute(select(tasks).where(room_repo.scope(tasks, store, identity.room_id), tasks.c.thread_id == identity.thread_id, tasks.c.turn_id == identity.turn_id)).mappings().one_or_none()
        return _storage_shared_1._task_from_row(room_repo.decode(row)) if row is not None else None

def _generation_change(store, identity, lease, execution, cancellation, *, status='indeterminate', now, fields, message='indeterminate task generation changed', replay=None):

    def guard(row):
        require_generations(row, status, execution, cancellation, message)
    return change(store, identity, now=now, fields=fields, lease=lease, replay=replay, guard=guard)

def resolve_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, settlement_id, status, result, clock):
    _storage_shared_1._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now, replay, params = _storage_shared_1._settlement(settlement_id, status, result, clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation, now=now, replay=replay, fields=settlement_fields(params))

def resolve_indeterminate_cancellation(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, cancel_id, clock):
    _storage_shared_1._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    cancel_id = _storage_shared_1._identifier(cancel_id, label='cancel_id')
    now = _storage_shared_1._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation, now=now, replay=_storage_shared_1._cancel_replay(cancel_id), message='indeterminate cancellation proof is stale', fields=dict(status='cancelled', cancel_generation=expected_cancel_generation + 1, cancel_id=cancel_id, terminal_at=now, updated_at=now))

def _queued(now, **extra):
    return dict(status='queued', run_gateway_id=None, run_process_generation=None, run_lease_generation=None, started_at=None, indeterminate_at=None, updated_at=now, **extra)

def requeue_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    _storage_shared_1._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _storage_shared_1._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation, now=now, fields=_queued(now))

def defer_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, reason, clock):
    return _defer_task(store, identity, lease, expected_execution_generation, expected_cancel_generation, reason, clock, status='indeterminate')

def defer_unconfirmed_stop(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, reason, clock):
    return _defer_task(store, identity, lease, expected_execution_generation, expected_cancel_generation, reason, clock, status='stopping')

def _defer_task(store, identity, lease, execution, cancellation, reason, clock, *, status):
    _storage_shared_1._expected_generations(lease, identity, execution, cancellation)
    reason = _storage_shared_1._identifier(reason, label='defer_reason')
    encoded = _storage_shared_1._canonical_json({'reason': reason, 'retryable': True})
    now = _storage_shared_1._timestamp(clock)

    def replay(row):
        deferred = _storage_shared_1._generations_match(row, 'deferred', execution, cancellation)
        return _storage_shared_1._task_from_row(row, idempotent=True) if deferred and row['result_json'] == encoded else None
    return _generation_change(store, identity, lease, execution, cancellation, status=status, now=now, replay=replay, message=f'{status} task generation changed', fields=dict(status='deferred', result_json=encoded, terminal_at=now, updated_at=now))

def reopen_deferred_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    _storage_shared_1._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _storage_shared_1._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation, status='deferred', now=now, message='deferred task generation changed', fields=dict(status='indeterminate', result_json=None, terminal_at=None, started_at=now, indeterminate_at=now, updated_at=now))

def requeue_deferred_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    _storage_shared_1._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _storage_shared_1._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation, status='deferred', now=now, message='deferred task generation changed', fields=_queued(now, result_json=None, terminal_at=None))

def prune_published_terminal_tasks(store, *, room_id, clock, retention_seconds=native.TERMINAL_TASK_RETENTION_SECONDS, retain=native.MAX_RETAINED_TERMINAL_TASKS):
    room_id = _storage_shared_1._identifier(room_id, label='room_id')
    now = _storage_shared_1._timestamp(clock)
    if retention_seconds <= 0:
        raise _storage_shared_1.DriverValidationError('retention_seconds must be positive')
    _storage_shared_1._bounded_int(retain, message='retain must be a non-negative integer')
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        rows = conn.execute(select(tasks.c.task_id, tasks.c.terminal_at).where(room_repo.scope(tasks, store, room_id), tasks.c.status.in_(_storage_shared_1.TERMINAL_STATUSES), ~room_work.unpublished(tasks, store)).order_by(tasks.c.terminal_at.desc(), tasks.c.task_id)).mappings()
        cutoff = now - float(retention_seconds)
        selected = [row['task_id'] for index, row in enumerate(rows) if index >= retain or (row['terminal_at'] is not None and row['terminal_at'] <= cutoff)][:_storage_shared_1.MAX_TASK_PRUNE_BATCH]
        if not selected:
            return 0
        return max(0, conn.execute(delete(tasks).where(room_repo.scope(tasks, store, room_id), tasks.c.task_id.in_(selected))).rowcount)

def settlement_fields(params):
    return dict(zip(('status', 'settlement_id', 'settlement_status', 'result_json', 'terminal_at', 'updated_at'), params))

def require_generations(row, status, execution, cancellation, message):
    if not _storage_shared_1._generations_match(row, status, execution, cancellation):
        raise _storage_shared_1.StaleTaskError(message)

def run_guard(attempt, message):

    def guard(row):
        require_generations(row, 'running', attempt.execution_generation, attempt.cancel_generation, message)
        if (row['run_gateway_id'], row['run_process_generation'], row['run_lease_generation']) != _storage_shared_1._run_fence(attempt.lease):
            raise _storage_shared_1.StaleTaskError(message)
    return guard

def settle_task(store, attempt, *, settlement_id, status, result, clock):
    now, replay, params = _storage_shared_1._settlement(settlement_id, status, result, clock)
    return change(store, attempt.identity, now=now, fields=settlement_fields(params), lease=attempt.lease, lease_first=False, replay=replay, guard=run_guard(attempt, 'task attempt is stale or cancelled'))

def settle_stopping_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, settlement_id, status, result, clock):
    _storage_shared_1._terminal_settlement_id(settlement_id, status)
    if expected_execution_generation < 1 or expected_cancel_generation < 1:
        raise _storage_shared_1.DriverValidationError('stopping settlement generations are invalid')
    now, replay, params = _storage_shared_1._settlement(settlement_id, status, result, clock)

    def guard(row):
        require_generations(row, 'stopping', expected_execution_generation, expected_cancel_generation, 'task completion lost the stop race')
    return change(store, identity, now=now, fields=settlement_fields(params), lease=lease, lease_first=False, replay=replay, guard=guard)

def requeue_not_admitted_task(store, attempt, *, clock):
    now = _storage_shared_1._timestamp(clock)
    _storage_shared_1._check_same_room(attempt.lease, attempt.identity)

    def replay(row):
        queued = _storage_shared_1._generations_match(row, 'queued', attempt.execution_generation, attempt.cancel_generation)
        cleared = (row['run_gateway_id'], row['run_process_generation'], row['run_lease_generation']) == (None, None, None)
        return _storage_shared_1._task_from_row(row, idempotent=True) if queued and cleared else None
    return change(store, attempt.identity, now=now, lease=attempt.lease, replay=replay, guard=run_guard(attempt, 'not-admitted task attempt lost its fence'), fields=dict(status='queued', run_gateway_id=None, run_process_generation=None, run_lease_generation=None, started_at=None, updated_at=now))

def _cancel_input(cancel_id, expected_cancel_generation, clock):
    cancel_id = _storage_shared_1._identifier(cancel_id, label='cancel_id')
    _storage_shared_1._cancel_generation(expected_cancel_generation)
    return (cancel_id, _storage_shared_1._timestamp(clock))

def cancel_task(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id, now = _cancel_input(cancel_id, expected_cancel_generation, clock)

    def guard(row):
        if row['status'] in _storage_shared_1.TERMINAL_STATUSES:
            raise _storage_shared_1.InvalidTaskTransitionError(f"cannot cancel task in state '{row['status']}'")
        if row['status'] not in {'queued', 'deferred'}:
            raise _storage_shared_1.InvalidTaskTransitionError('running work requires acknowledged two-phase cancellation')
        _storage_shared_1._require_cancel_generation(row, expected_cancel_generation)
    return change(store, identity, now=now, replay=_storage_shared_1._cancel_replay(cancel_id), guard=guard, fields=dict(status='cancelled', cancel_generation=expected_cancel_generation + 1, cancel_id=cancel_id, terminal_at=now, updated_at=now))

def begin_task_cancel(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id, now = _cancel_input(cancel_id, expected_cancel_generation, clock)

    def guard(row):
        if row['status'] in _storage_shared_1.TERMINAL_STATUSES or row['status'] == 'queued':
            raise _storage_shared_1.InvalidTaskTransitionError(f"cannot request remote stop in state '{row['status']}'")
        _storage_shared_1._require_cancel_generation(row, expected_cancel_generation)
        if row['status'] not in {'running', 'indeterminate'}:
            raise _storage_shared_1.StaleTaskError('task changed during stop request')
    return change(store, identity, now=now, replay=_storage_shared_1._cancel_replay(cancel_id, 'stopping'), guard=guard, fields=dict(status='stopping', cancel_generation=expected_cancel_generation + 1, cancel_id=cancel_id, updated_at=now))

def complete_task_cancel(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id = _storage_shared_1._identifier(cancel_id, label='cancel_id')
    now = _storage_shared_1._timestamp(clock)

    def guard(row):
        if (row['status'], row['cancel_id'], int(row['cancel_generation'])) != ('stopping', cancel_id, expected_cancel_generation):
            raise _storage_shared_1.StaleTaskError('task stop acknowledgement is stale')
    return change(store, identity, now=now, replay=_storage_shared_1._cancel_replay(cancel_id), guard=guard, fields=dict(status='cancelled', terminal_at=now, updated_at=now))


def room_task_summary(store, *, room_id, statuses):
    """Counts and shown rows share the existing REPEATABLE READ snapshot."""
    from sqlalchemy import func
    room_id = native._identifier(room_id, label="room_id")
    statuses = tuple(statuses)
    if any(status not in native.TASK_STATUSES for status in statuses):
        raise native.DriverValidationError("invalid task status")
    with store.read() as conn:
        counts = {status: int(count) for status, count in conn.execute(
            select(tasks.c.status, func.count()).where(repo.scope(tasks, store, room_id)).group_by(tasks.c.status))}
        statement = select(tasks).where(repo.scope(tasks, store, room_id), tasks.c.status.in_(statuses)).order_by(
            tasks.c.source_event_seq, tasks.c.created_at, tasks.c.task_id)
        rows = conn.execute(statement).mappings().all() if statuses else []
        return counts, [native._task_from_row(repo.record(row)) for row in rows]


def room_change_rows(store, statuses=native.SHOWN_TASK_STATUSES):
    """Only live rooms and the visible task generations contribute to change notifications."""
    from sqlalchemy import and_
    from hermes_db.tables.rooms import rooms
    join = rooms.outerjoin(tasks, and_(tasks.c.store_id == rooms.c.store_id,
        tasks.c.room_id == rooms.c.room_id, tasks.c.status.in_(statuses)))
    statement = select(rooms.c.room_id, rooms.c.next_seq, rooms.c.revision,
        tasks.c.task_id, tasks.c.status, tasks.c.execution_generation, tasks.c.cancel_generation).select_from(join).where(
            repo.scope(rooms, store), rooms.c.disbanded_at.is_(None))
    grouped = {}
    with store.read() as conn:
        for room_id, seq, revision, task_id, status, execution, cancellation in conn.execute(statement):
            entry = grouped.setdefault(room_id, (seq, revision, []))
            if task_id is not None:
                entry[2].append((task_id, status, execution, cancellation))
    return {room_id: native.RoomChangeRows(seq, revision, tuple(sorted(rows)))
            for room_id, (seq, revision, rows) in grouped.items()}
