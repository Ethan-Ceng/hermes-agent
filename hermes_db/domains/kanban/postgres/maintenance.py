"""Kanban maintenance workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1__
from hermes_db.domains.kanban import rules as _storage_shared_1_
import logging
_kanban_logger = logging.getLogger("hermes_cli.kanban_db")
from hermes_db.domains.kanban import rules as _storage_shared_1
import time
from collections import Counter
from sqlalchemy import select
from hermes_db.domains.kanban.postgres.runs import record_failure
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo, evidence as evidence_repo
from hermes_db.tables.kanban import runs, kanban_boards, tasks
from hermes_db.domains.kanban.postgres import files
from hermes_db.tables.kanban_file_jobs import file_jobs
from hermes_db.core.values import decode_text, encode_text


def _violation_streak(conn, store, task_id):

    rows = conn.execute(select(runs.c.outcome, runs.c.error, runs.c.metadata).where(repo.key(store, task_id, runs), runs.c.ended_at.is_not(None)).order_by(runs.c.id.desc()).limit(_storage_shared_1__._PROTOCOL_VIOLATION_SCAN_LIMIT)).mappings()
    streak = 0
    for raw in rows:
        row = repo.decode_record(raw)
        if row['outcome'] == 'rate_limited':
            continue
        head = (row['error'] or '').partition(_storage_shared_1__.WORKER_OUTPUT_SEP)[0]
        if row['outcome'] != 'crashed' or not (_storage_shared_1._json_dict(row['metadata']).get('protocol_violation') or 'protocol violation' in head):
            break
        streak += 1
    return streak

def _charge(conn, store, task, dead, frequencies):

    if dead.rate_limited:
        return False
    extra = {'pid': task['worker_pid'], 'claimer': task['claim_lock']}
    limit, force = (_storage_shared_1_.DEFAULT_FAILURE_LIMIT, False)
    if dead.protocol_violation:
        streak = _violation_streak(conn, store, task['id'])
        limit = int(task['max_retries']) if task['max_retries'] is not None else _storage_shared_1__._PROTOCOL_VIOLATION_FAILURE_LIMIT
        if streak < limit:
            return False
        force = True
        extra.update(protocol_violations=streak, protocol_violation_limit=limit)
    elif dead.terminal_provider:
        force = True
        extra['terminal_provider'] = True
    elif frequencies[_storage_shared_1__._error_fingerprint(dead.error_text)] >= 3:
        limit = 1
        extra['sticky'] = True
    return record_failure(conn, store, repo.require_task(conn, store, task['id']), dead.error_text, outcome='crashed', failure_limit=limit, force_trip=force, event_payload_extra=extra)

def _close(conn, store, evidence, dead, frequencies):
    task = evidence.task
    retry = run_repo.retry_status(conn, store, task['id'], task['current_run_id'])
    dead.event_payload['retry_status'] = retry
    repo.task_update(conn, store, task['id'], status=retry, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
    run_id = run_repo.close_run(conn, store, task, outcome=dead.run_outcome, error=dead.error_text, metadata=dead.event_payload)
    repo.event(conn, store, task['id'], dead.event_kind, dead.event_payload, run_id)
    if dead.rate_limited or dead.protocol_violation:
        repo.task_update(conn, store, task['id'], last_failure_error=dead.error_text[:500])
    blocked = _charge(conn, store, task, dead, frequencies)
    hook = dict(task_id=task['id'], assignee=task['assignee'], run_id=run_id, worker_pid=task['worker_pid'], exit_kind=dead.kind, exit_code=dead.code, outcome=dead.run_outcome, retry_status=retry)
    return (blocked, hook)




def _elapsed(evidence, now):
    started = evidence.run.get('started_at')
    if started is None:
        started = evidence.task['started_at']
    return None if started is None else now - started



def finish(store, evidence, *, outcome, error, payload, charge=False, failure_limit=None, comment=None, run_metadata=None, event_kind=None):

    from hermes_db.domains.kanban.postgres.runs import record_failure
    task = evidence.task
    task_id = task['id']
    with store.write() as conn:
        if not evidence_repo.unchanged(conn, store, evidence):
            return None
        retry = run_repo.retry_status(conn, store, task_id, task['current_run_id'])
        payload = {**payload, 'retry_status': retry}
        repo.task_update(conn, store, task_id, status=retry, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None, last_heartbeat_at=None)
        run_id = run_repo.close_run(conn, store, task, outcome=outcome, error=error, metadata=payload if run_metadata is None else run_metadata)
        repo.event(conn, store, task_id, event_kind or outcome, payload, run_id)
        if comment:
            repo.comment(conn, store, task_id, 'dispatcher', comment, int(time.time()))
        if charge:
            record_failure(conn, store, repo.require_task(conn, store, task_id), error, outcome=outcome, failure_limit=_storage_shared_1_.DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit)
    return {'run_id': run_id, 'retry_status': retry}


def extend_claim(store, evidence, now, expires, *, termination=None, reason=None):
    task = evidence.task
    task_id = task['id']
    deferred = termination is not None
    with store.write() as conn:
        if not evidence_repo.unchanged(conn, store, evidence):
            return
        repo.task_update(conn, store, task_id, claim_expires=expires)
        run_id = task['current_run_id']
        if run_id is not None:
            run_repo.update_run(conn, store, run_id, claim_expires=expires)
        payload = {'reason': reason or 'pid_alive', 'claim_lock': task['claim_lock'], 'claim_expires_now': expires}
        if deferred:
            payload.update(termination)
        else:
            payload.update(worker_pid=task['worker_pid'], claim_expires_was=task['claim_expires'], last_heartbeat_at=task['last_heartbeat_at'])
        repo.event(conn, store, task_id, 'reclaim_deferred' if deferred else 'claim_extended', payload, run_id)


def reap_terminal_claim(store, run, alive, termination, pid, fingerprint):
    with store.write() as conn:
        if run_repo.get(conn, store, run['id']) != run:
            return False
        run_repo.update_run(conn, store, run['id'], worker_pid=None, worker_started_at=None)
        if alive:
            repo.event(conn, store, run['task_id'], 'terminal_worker_reaped', {'pid': pid, 'worker_started_at': fingerprint, **termination}, run['id'])
    return alive


def terminal_worker_rows(store, cutoff):
    with store.read() as conn:
        rows = [repo.decode_record(row) for row in conn.execute(select(runs).where(repo.scope(runs, store), runs.c.ended_at <= cutoff, runs.c.worker_pid.is_not(None), runs.c.worker_started_at.is_not(None))).mappings()]
    return rows


def pending_file_boards(resource):
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        jobs = list(conn.scalars(select(file_jobs.c.board_id).where(file_jobs.c.store_id == owned, file_jobs.c.owner_home == encode_text(str(resource.scope.profile_home)), (file_jobs.c.state != 'done') | (file_jobs.c.action == 'import'))))
    return jobs


def terminal_workspace_rows(resource):
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        rows = list(conn.execute(select(tasks.c.board_id, kanban_boards.c.slug, tasks.c.id).join(kanban_boards, (tasks.c.store_id == kanban_boards.c.store_id) & (tasks.c.board_id == kanban_boards.c.board_id)).where(tasks.c.store_id == owned, tasks.c.status.in_((b'done', b'archived', b'failed', b'cancelled')), tasks.c.workspace_path.is_not(None), tasks.c.workspace_kind.in_((b'scratch', b'worktree')))))
    return rows


def pending_workspace_rows(resource):
    from hermes_db.tables.kanban_workspaces import paths
    with resource.read() as conn:
        pending = list(conn.execute(select(paths.c.path_key, paths.c.cleanup_token, paths.c.cleanup_payload).where(paths.c.store_id == resource.scope.require_store_id(), paths.c.cleanup_token.is_not(None))))
    return pending


def live_import_stages(resource):
    with resource.write() as conn:
        files.lock_files(conn, resource)
    with resource.read() as conn:
        live = {decode_text(value) for value in conn.scalars(select(file_jobs.c.stage_root).where(file_jobs.c.store_id == resource.scope.require_store_id(), file_jobs.c.stage_root.is_not(None)))}
    return live
