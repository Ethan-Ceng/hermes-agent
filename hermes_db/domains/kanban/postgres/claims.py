"""Kanban claims workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
import time
from sqlalchemy import update
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo
from hermes_db.domains.kanban.postgres.catalog import _unsatisfied
from hermes_db.tables.kanban import tasks

def _reject_parents(conn, store, row, source):
    if row['status'] == source and (source == 'ready' or row['claim_lock'] is None):
        repo.task_update(conn, store, row['id'], status='todo')
        if source == 'review':
            repo.event(conn, store, row['id'], 'dependency_wait', {'reason': 'parent_reopened', 'source_status': 'review'})
    if source == 'ready':
        repo.event(conn, store, row['id'], 'claim_rejected', {'reason': 'parents_not_done'})

def _close_dangling(conn, store, row, now, note='invariant recovery on re-claim'):
    run_id = row['current_run_id']
    if run_id is not None:
        run = run_repo.get(conn, store, run_id)
        if run and run['ended_at'] is None:
            run_repo.update_run(conn, store, run_id, status='reclaimed', outcome='reclaimed', summary=run['summary'] if run['summary'] is not None else note, ended_at=now, claim_lock=None, claim_expires=None, worker_pid=None)




def heartbeat_worker(store, task_id, *, note=None, expected_run_id=None):
    now = int(time.time())
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] != 'running' or (expected_run_id is not None and row['current_run_id'] != int(expected_run_id)):
            return store.command_result(conn, False)
        repo.task_update(conn, store, task_id, last_heartbeat_at=now)
        run_id = row['current_run_id']
        if run_id is not None:
            run_repo.update_run(conn, store, run_id, last_heartbeat_at=now)
        repo.event(conn, store, task_id, 'heartbeat', {'note': note} if note else None, run_id)
        store.command_result(conn, True)
    return True



def _classify_blocked(conn, store, row, kind, reason, expected_run_id):
    if kind is None or expected_run_id is not None or row['block_kind'] is not None or (row['current_run_id'] is not None):
        return False
    repo.task_update(conn, store, row['id'], block_kind=kind, block_recurrences=1)
    repo.event(conn, store, row['id'], 'blocked', {'kind': kind, 'reason': reason, 'classified_in_place': True})
    return True


def unblock_task(store, task_id):
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] not in {'blocked', 'scheduled'}:
            return store.command_result(conn, False)
        resume = repo.resume_status(repo.history(conn, store, task_id)) if row['status'] == 'blocked' else 'ready'
        _close_dangling(conn, store, row, int(time.time()), 'invariant recovery on unblock')
        status = 'todo' if _unsatisfied(conn, store, task_id) else resume
        repo.task_update(conn, store, task_id, status=status, current_run_id=None, consecutive_failures=0, last_failure_error=None)
        payload = {'status': status, 'resume_status': resume} if status != 'ready' or resume != 'ready' else None
        repo.event(conn, store, task_id, 'unblocked', payload)
        store.command_result(conn, True)
    return True

def schedule_task(store, task_id, *, reason=None, expected_run_id=None):
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] not in {'todo', 'ready', 'running', 'blocked'}:
            return store.command_result(conn, False)
        if expected_run_id is not None and row['current_run_id'] != int(expected_run_id):
            return store.command_result(conn, False)
        repo.task_update(conn, store, task_id, status='scheduled', claim_lock=None, claim_expires=None, worker_pid=None)
        run_id = run_repo.close_run(conn, store, row, outcome='scheduled', status='scheduled', summary=reason)
        if run_id is None and reason:
            run_id = run_repo.synthesize(conn, store, row, outcome='scheduled', summary=reason)
        repo.event(conn, store, task_id, 'scheduled', {'reason': reason}, run_id)
        store.command_result(conn, True)
    return True

def _promotion_error(conn, store, task_id):
    task = repo.get(conn, store, task_id)
    if task is None:
        return f'task {task_id} not found'
    if task['status'] not in {'todo', 'blocked'}:
        return f"task {task_id} is {task['status']!r}; promote only applies to 'todo' or 'blocked'"
    parents = [tid for tid, _status in _unsatisfied(conn, store, task_id)]
    if parents:
        return f"unsatisfied parent dependencies: {', '.join(parents)} (the ready -> running claim re-checks parents, so promotion cannot bypass them; complete the parents or drop the link with `hermes kanban unlink <parent_id> {task_id}`)"
    return None

def promote_task(store, task_id, *, actor, reason=None, dry_run=False):
    if dry_run:
        with store.read() as conn:
            error = _promotion_error(conn, store, task_id)
            return (error is None, error)
    with store.write() as conn:
        error = _promotion_error(conn, store, task_id)
        if error:
            return (False, error)
        if repo.task_update(conn, store, task_id, status='ready') != 1:
            return (False, f'task {task_id} status changed during promotion')
        repo.event(conn, store, task_id, 'promoted_manual', {'actor': actor, 'reason': reason})
    return (True, None)


def claim_prepared(store, task_id, source, now, lock, expires, *, dispatch_permit=None):
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return store.command_result(conn, None), None
        if _unsatisfied(conn, store, task_id):
            _reject_parents(conn, store, row, source)
            return store.command_result(conn, None), None
        if row['status'] != source or row['claim_lock'] is not None:
            return store.command_result(conn, None), None
        if dispatch_permit is not None and (not dispatch_permit.admit(conn, store, row)):
            return store.command_result(conn, None), None
        if source == 'ready':
            _close_dangling(conn, store, row, now)
        changed = conn.execute(update(tasks).where(repo.key(store, task_id), tasks.c.status == source.encode(), tasks.c.claim_lock.is_(None)).values(status=b'running', claim_lock=lock.encode(), claim_expires=expires, started_at=row['started_at'] if row['started_at'] is not None else now)).rowcount
        if changed != 1:
            return store.command_result(conn, None), None
        run_id = run_repo.open_run(conn, store, row, lock, expires, now)
        repo.task_update(conn, store, task_id, current_run_id=run_id)
        extra = {'source_status': 'review'} if source == 'review' else {}
        repo.event(conn, store, task_id, 'claimed', {'lock': lock, 'expires': expires, 'run_id': run_id, **extra}, run_id)
        claimed = store.result_values.task(repo.get(conn, store, task_id))
        from hermes_db.domains.kanban.postgres.effects import enqueue, hook_step
        effect_id = enqueue(conn, store, [hook_step(store, repo.get(conn, store, task_id), 'kanban_task_claimed', run_id)]) if source == 'ready' else None
        store.command_result(conn, claimed)
    return claimed, effect_id


def heartbeat_prepared(store, task_id, lock, expires):
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] != 'running' or row['claim_lock'] != lock:
            return store.command_result(conn, False)
        repo.task_update(conn, store, task_id, claim_expires=expires)
        if row['current_run_id'] is not None:
            run_repo.update_run(conn, store, row['current_run_id'], claim_expires=expires)
        store.command_result(conn, True)
    return True


def reclaim_snapshot(store, task_id):
    with store.read() as conn:
        snapshot = repo.get(conn, store, task_id)
    return snapshot


def reclaim_prepared(store, task_id, snapshot, termination, *, reason=None):
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        fields = ('status', 'current_run_id', 'claim_lock', 'worker_pid', 'worker_started_at')
        if row is None or any(row[field] != snapshot[field] for field in fields) or row['status'] not in {'running', 'ready', 'blocked'}:
            return False
        retry = run_repo.retry_status(conn, store, task_id, row['current_run_id'])
        repo.task_update(conn, store, task_id, status=retry, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None, consecutive_failures=0, last_failure_error=None)
        error = f'manual_reclaim: {reason}' if reason else f"manual_reclaim lock={snapshot['claim_lock']}"
        run_id = run_repo.close_run(conn, store, row, outcome='reclaimed', status='reclaimed', error=error, metadata=termination)
        repo.event(conn, store, task_id, 'reclaimed', {'manual': True, 'reason': reason, 'prev_lock': snapshot['claim_lock'], 'retry_status': retry, **termination}, run_id)
        store.command_result(conn, True)
    return True


def block_prepared(store, task_id, *, reason=None, kind=None, expected_run_id=None):

    from hermes_cli.kanban_block_policy import block_transition
    if kind is not None and kind not in _storage_shared_1.VALID_BLOCK_KINDS:
        raise ValueError(f'block kind must be one of {sorted(_storage_shared_1.VALID_BLOCK_KINDS)} or None')
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return store.command_result(conn, False), None
        if row['status'] == 'blocked':
            return store.command_result(conn, _classify_blocked(conn, store, row, kind, reason, expected_run_id)), None
        if row['status'] not in {'running', 'ready'} or (expected_run_id is not None and row['current_run_id'] != int(expected_run_id)):
            return store.command_result(conn, False), None
        source = run_repo.retry_status(conn, store, task_id, row['current_run_id']) if row['status'] == 'running' else 'ready'
        requested = kind
        if kind == 'dependency' and (not _unsatisfied(conn, store, task_id)):
            kind = 'needs_input'
        status, event, values, payload = block_transition(kind, reason, source, prev_kind=row['block_kind'], prev_recurrences=int(row['block_recurrences'] or 0), recurrence_limit=_storage_shared_1.BLOCK_RECURRENCE_LIMIT)
        if requested != kind:
            payload.update(requested_kind=requested, rekind_reason='no_open_parent')
        repo.task_update(conn, store, task_id, status=status, claim_lock=None, claim_expires=None, worker_pid=None, **values)
        run_id = run_repo.close_run(conn, store, row, outcome='blocked', status='blocked', summary=reason)
        if run_id is None and reason:
            run_id = run_repo.synthesize(conn, store, row, outcome='blocked', summary=reason)
        repo.event(conn, store, task_id, event, payload, run_id)
        from hermes_db.domains.kanban.postgres.effects import enqueue, hook_step
        effect_id = enqueue(conn, store, [hook_step(store, repo.get(conn, store, task_id), 'kanban_task_blocked', run_id, reason=reason)])
        store.command_result(conn, True)
    return True, effect_id
