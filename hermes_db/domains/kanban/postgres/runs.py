"""Kanban runs workflow; original connection, fence and off-connection effect boundaries are preserved."""
from sqlalchemy import func, select, and_, update
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban import tasks, runs, events
from hermes_db.core.values import encode_text, decode_text
from hermes_cli.kanban_failure_policy import failure_budget
import json
import time

def get_run(store, run_id):

    with store.read() as conn:
        row = get(conn, store, run_id)
        return store.result_values.run(row) if row is not None else None

def list_runs(store, task_id, *, include_active=True, state_type=None, state_name=None):

    if (state_type is None) ^ (state_name is None):
        raise ValueError('state_type and state_name must both be set or both omitted')
    if state_type is not None and state_type not in {'status', 'outcome'}:
        raise ValueError("state_type must be 'status' or 'outcome'")
    query = select(runs).where(repo.key(store, task_id, runs))
    if not include_active:
        query = query.where(runs.c.ended_at.is_not(None))
    if state_type is not None:
        query = query.where(runs.c[state_type] == encode_text(state_name))
    with store.read() as conn:
        return [store.result_values.run(repo.decode_record(row)) for row in conn.execute(query.order_by(runs.c.started_at, runs.c.id)).mappings()]

def latest_run(store, task_id):

    with store.read() as conn:
        row = conn.execute(select(runs).where(repo.key(store, task_id, runs)).order_by(runs.c.started_at.desc(), runs.c.id.desc()).limit(1)).mappings().one_or_none()
        return store.result_values.run(repo.decode_record(row)) if row is not None else None

def latest_summaries(store, task_ids):
    ids = list(task_ids)
    ranked = select(runs.c.task_id, runs.c.summary, func.row_number().over(partition_by=runs.c.task_id, order_by=(func.coalesce(runs.c.ended_at, runs.c.started_at).desc(), runs.c.id.desc())).label('rank'))
    ranked = ranked.where(repo.scope(runs, store), runs.c.task_id.in_([encode_text(tid) for tid in ids]), runs.c.summary.is_not(None), runs.c.summary != b'').subquery()
    with store.read() as conn:
        return {decode_text(tid): decode_text(summary) for tid, summary in conn.execute(select(ranked.c.task_id, ranked.c.summary).where(ranked.c.rank == 1))}

def latest_summary(store, task_id):
    return latest_summaries(store, [task_id]).get(task_id)

def current_run_started_ats(store, task_ids):
    query = select(tasks.c.id, runs.c.started_at).join(runs, (tasks.c.store_id == runs.c.store_id) & (tasks.c.board_id == runs.c.board_id) & (tasks.c.id == runs.c.task_id) & (tasks.c.current_run_id == runs.c.id))
    with store.read() as conn:
        return {decode_text(tid): stamp for tid, stamp in conn.execute(query.where(repo.scope(tasks, store), tasks.c.id.in_([encode_text(tid) for tid in task_ids])))}

def _retry_status_for_run(store, task_id, run_id=None):
    with store.read() as conn:
        row = repo.get(conn, store, task_id)
        current = row['current_run_id'] if row is not None else None
        return retry_status(conn, store, task_id, current if run_id is None else run_id)

def goal_run_status(store, task_id, expected_run_id=None):
    from hermes_db.domains.kanban.rules import _RUN_OUTCOME_TERMINAL_STATUS
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return None
        if expected_run_id is not None:
            run = get(conn, store, expected_run_id)
            outcome = run['outcome'] if run is not None and run['task_id'] == task_id else None
            terminal = _RUN_OUTCOME_TERMINAL_STATUS.get(outcome)
            if terminal is not None:
                return terminal
            if outcome is not None or task['current_run_id'] != int(expected_run_id):
                return 'superseded'
        if task['status'] in {'ready', 'todo'}:
            kind = conn.scalar(select(events.c.kind).where(repo.key(store, task_id, events)).order_by(events.c.id.desc()).limit(1))
            if kind == b'changes_requested':
                return 'changes_requested'
        return task['status']

def recent_profile_completions(store, profile, exclude_task_id, *, limit=5):
    query = select(tasks.c.id, tasks.c.title, runs.c.summary, runs.c.ended_at).join(runs, (tasks.c.store_id == runs.c.store_id) & (tasks.c.board_id == runs.c.board_id) & (tasks.c.id == runs.c.task_id))
    query = query.where(repo.scope(tasks, store), runs.c.profile == encode_text(profile), runs.c.task_id != encode_text(exclude_task_id), runs.c.outcome == b'completed')
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(query.order_by(runs.c.ended_at.desc().nulls_last()).limit(int(limit))).mappings()]

def _retry_failure(conn, store, task, error, outcome, failures, retry, release_claim, end_run, infrastructure):
    values = {'consecutive_failures': failures, 'last_failure_error': error}
    if release_claim:
        values.update(status=retry, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
    repo.task_update(conn, store, task['id'], **values)
    if end_run:
        detail = {'failures': failures, 'retry_status': retry}
        if infrastructure:
            detail['infrastructure'] = True
        run_id = close_run(conn, store, task, outcome=outcome, status=outcome, error=error, metadata=detail)
        repo.event(conn, store, task['id'], outcome, {'error': error, **detail}, run_id)
    return False

def _trip_failure(conn, store, task, error, outcome, budget, retry, release_claim, end_run, force_trip, extra):
    failures, limit, source, _trip = budget
    values = {'consecutive_failures': failures, 'last_failure_error': error}
    if task['status'] in {'running', 'ready', 'review'}:
        values['status'] = 'blocked'
    if release_claim:
        values.update(claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
    repo.task_update(conn, store, task['id'], **values)
    payload = {'failures': failures, 'effective_limit': limit, 'limit_source': source, 'error': error, 'trigger_outcome': outcome, 'retry_status': retry}
    run_id = None
    if end_run:
        metadata = {key: value for key, value in payload.items() if key != 'error'}
        run_id = close_run(conn, store, task, outcome='gave_up', status='gave_up', error=error, metadata=metadata)
    if force_trip:
        payload['sticky'] = True
    if extra:
        payload.update(extra)
    repo.event(conn, store, task['id'], 'gave_up', payload, run_id)
    return True

def record_failure(conn, store, task, error, *, outcome, failure_limit, force_trip=False, release_claim=False, end_run=False, event_payload_extra=None, infrastructure=False):
    retry = retry_status(conn, store, task['id'], task['current_run_id']) if release_claim else 'review' if task['status'] == 'review' else 'ready'
    budget = failure_budget(task, failure_limit, force_trip, infrastructure)
    error = error[:500]
    if not budget[3]:
        return _retry_failure(conn, store, task, error, outcome, budget[0], retry, release_claim, end_run, infrastructure)
    return _trip_failure(conn, store, task, error, outcome, budget, retry, release_claim, end_run, force_trip, event_payload_extra)

def _record_task_failure(store, task_id, error, *, outcome, failure_limit=None, force_trip=False, release_claim=False, end_run=False, event_payload_extra=None, infrastructure=False, expected_run_id=None):
    from hermes_db.domains.kanban.rules import DEFAULT_FAILURE_LIMIT
    failure_limit = DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task['status'] in {'done', 'archived'}:
            return store.command_result(conn, False)
        if expected_run_id is not None and task['current_run_id'] != int(expected_run_id):
            return store.command_result(conn, False)
        if release_claim and task['status'] != 'running':
            return store.command_result(conn, False)
        result = record_failure(conn, store, task, error, outcome=outcome, failure_limit=failure_limit, force_trip=force_trip, release_claim=release_claim, end_run=end_run, event_payload_extra=event_payload_extra, infrastructure=infrastructure)
        return store.command_result(conn, result)

def _clear_failure_counter(store, task_id):
    with store.write() as conn:
        repo.task_update(conn, store, task_id, consecutive_failures=0, last_failure_error=None)
TEXT_FIELDS = {'task_id', 'profile', 'step_key', 'status', 'claim_lock', 'worker_started_at', 'outcome', 'summary', 'metadata', 'error'}
_UNSET = object()

def encode(values):
    return {name: encode_text(value) if name in TEXT_FIELDS else value for name, value in values.items()}

def key(store, run_id):
    return and_(repo.scope(runs, store), runs.c.id == int(run_id))

def get(conn, store, run_id):
    row = conn.execute(select(runs).where(key(store, run_id))).mappings().one_or_none()
    return repo.decode_record(row) if row is not None else None

def update_run(conn, store, run_id, **values):
    return conn.execute(update(runs).where(key(store, run_id)).values(**encode(values))).rowcount

def open_run(conn, store, task, lock, expires, now):
    values = dict(task_id=task['id'], profile=task['assignee'], step_key=task['current_step_key'], status='running', claim_lock=lock, claim_expires=expires, max_runtime_seconds=task['max_runtime_seconds'], started_at=now)
    return conn.scalar(runs.insert().values(**repo.owner(store), **encode(values)).returning(runs.c.id))

def close_run(conn, store, task, *, outcome, status=None, summary=None, error=None, metadata=None):
    run_id = task['current_run_id']
    if run_id is None:
        return None
    values = dict(status=status or outcome, outcome=outcome, summary=summary, error=error, metadata=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None, ended_at=int(time.time()), claim_expires=None)
    conn.execute(update(runs).where(key(store, run_id), runs.c.task_id == encode_text(task['id']), runs.c.ended_at.is_(None)).values(**encode(values)))
    repo.task_update(conn, store, task['id'], current_run_id=None)
    return run_id

def retry_status(conn, store, task_id, run_id):
    if run_id is None:
        return 'ready'
    payload = conn.scalar(select(events.c.payload).where(repo.key(store, task_id, events), events.c.run_id == int(run_id), events.c.kind == b'claimed').order_by(events.c.id.desc()).limit(1))
    from hermes_db.core.values import decode_text
    from hermes_db.domains.kanban.rules import _json_dict
    data = _json_dict(decode_text(payload))
    return 'review' if data.get('source_status') == 'review' else 'ready'

def synthesize(conn, store, task, *, outcome, summary=None, error=None, metadata=None, profile=_UNSET):
    now = int(time.time())
    values = dict(task_id=task['id'], profile=task['assignee'] if profile is _UNSET else profile, step_key=task['current_step_key'], status=outcome, outcome=outcome, summary=summary, error=error, metadata=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None, started_at=now, ended_at=now)
    return conn.scalar(runs.insert().values(**repo.owner(store), **encode(values)).returning(runs.c.id))
