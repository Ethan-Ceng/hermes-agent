"""Kanban maintenance workflow; original connection, fence and off-connection effect boundaries are preserved."""
import time
from collections import Counter
from sqlalchemy import select
from hermes_db.domains.kanban.postgres.runs import record_failure
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo, evidence as evidence_repo
from hermes_db.tables.kanban import runs, kanban_boards, tasks
import os
import psutil
import re
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.domains.kanban.routing.files import board_files
from hermes_db.domains.kanban.postgres import files
from hermes_db.tables.kanban_file_jobs import file_jobs
from hermes_db.core.values import decode_text, encode_text

def _prepare(store, board):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch, kanban_owner_recovery as recovery
    prepared = []
    now = time.time()
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if not task['worker_pid'] or not (task['claim_lock'] or '').startswith(kb._host_prefix()):
            continue
        started = task['started_at']
        if started is not None and now - started < kb._resolve_crash_grace_seconds():
            continue
        if kb._worker_alive(task['worker_pid'], task['worker_started_at']):
            continue
        if recovery.owner_reclaim_blocked(evidence, task['id'], crash_sweep=True):
            continue
        code = recovery.managed_run_exit_code(evidence, task['id'], task['worker_pid'], task['claim_lock'])
        dead = dispatch._classify_dead_worker(task['worker_pid'], task['claim_lock'], code, task_id=task['id'], board=board)
        recovery.apply_attempt_note(evidence, task['id'], task['worker_pid'], dead)
        prepared.append((evidence, dead))
    return prepared

def _violation_streak(conn, store, task_id):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    rows = conn.execute(select(runs.c.outcome, runs.c.error, runs.c.metadata).where(repo.key(store, task_id, runs), runs.c.ended_at.is_not(None)).order_by(runs.c.id.desc()).limit(dispatch._PROTOCOL_VIOLATION_SCAN_LIMIT)).mappings()
    streak = 0
    for raw in rows:
        row = repo.decode_record(raw)
        if row['outcome'] == 'rate_limited':
            continue
        head = (row['error'] or '').partition(dispatch.WORKER_OUTPUT_SEP)[0]
        if row['outcome'] != 'crashed' or not (kb._json_dict(row['metadata']).get('protocol_violation') or 'protocol violation' in head):
            break
        streak += 1
    return streak

def _charge(conn, store, task, dead, frequencies):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    if dead.rate_limited:
        return False
    extra = {'pid': task['worker_pid'], 'claimer': task['claim_lock']}
    limit, force = (kb.DEFAULT_FAILURE_LIMIT, False)
    if dead.protocol_violation:
        streak = _violation_streak(conn, store, task['id'])
        limit = int(task['max_retries']) if task['max_retries'] is not None else dispatch._PROTOCOL_VIOLATION_FAILURE_LIMIT
        if streak < limit:
            return False
        force = True
        extra.update(protocol_violations=streak, protocol_violation_limit=limit)
    elif dead.terminal_provider:
        force = True
        extra['terminal_provider'] = True
    elif frequencies[dispatch._error_fingerprint(dead.error_text)] >= 3:
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

def detect_crashed_workers(store, board=None):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    prepared = _prepare(store, store.slug if board is None else board)
    crashed, limited, blocked, hooks = ([], [], [], [])
    if prepared:
        with store.write() as conn:
            accepted = [(evidence, dead) for evidence, dead in prepared if evidence_repo.unchanged(conn, store, evidence)]
            frequencies = Counter((dispatch._error_fingerprint(dead.error_text) for _, dead in accepted if not dead.rate_limited))
            for evidence, dead in accepted:
                tripped, hook = _close(conn, store, evidence, dead, frequencies)
                (limited if dead.rate_limited else crashed).append(evidence.task['id'])
                if tripped:
                    blocked.append(evidence.task['id'])
                hooks.append(hook)
    dispatch.detect_crashed_workers._last_auto_blocked = blocked
    dispatch.detect_crashed_workers._last_rate_limited = limited
    if kb._kanban_observer_consumed('on_kanban_worker_exited'):
        for hook in hooks:
            kb._fire_kanban_lifecycle_hook('on_kanban_worker_exited', hook.pop('task_id'), board=store.slug, **hook)
    return crashed

def release_stale_claims(store, *, signal_fn=None, failure_limit=None):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    now = int(time.time())
    reclaimed = 0
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        expires = task['claim_expires']
        if expires is None or expires >= now or recovery.owner_reclaim_blocked(evidence, task['id']):
            continue
        local = (task['claim_lock'] or '').startswith(kb._host_prefix())
        heartbeat = task['last_heartbeat_at']
        stale = heartbeat is not None and now - heartbeat > kb.DEFAULT_CLAIM_HEARTBEAT_MAX_STALE_SECONDS
        if local and task['worker_pid'] and kb._worker_alive(task['worker_pid'], task['worker_started_at']) and (not stale):
            extend(store, evidence, now)
            continue
        termination = terminate(store, evidence, signal_fn, 'ttl_expired_worker_alive')
        if termination is None:
            continue
        payload = {'stale_lock': task['claim_lock'], 'worker_pid': task['worker_pid'], 'claim_expires': expires, 'last_heartbeat_at': heartbeat, 'now': now, 'host_local': local, 'heartbeat_stale': stale, **termination}
        result = finish(store, evidence, outcome='reclaimed', error=recovery.reclaim_error(evidence, task['id'], task['claim_lock']), payload=payload, run_metadata=termination, charge=True, failure_limit=failure_limit)
        if result is None:
            continue
        reclaimed += 1
        if kb._kanban_observer_consumed('on_kanban_worker_stale_claim'):
            kb._fire_kanban_lifecycle_hook('on_kanban_worker_stale_claim', task['id'], board=store.slug, assignee=task['assignee'], run_id=result['run_id'], worker_pid=task['worker_pid'], heartbeat_stale=stale, retry_status=result['retry_status'])
    return reclaimed

def reconcile_orphaned_running(store):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    reconciled = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if task['claim_lock'] is not None and task['claim_expires'] is not None:
            continue
        if recovery.owner_reclaim_blocked(evidence, task['id']):
            continue
        if task['worker_pid'] and kb._worker_alive(task['worker_pid'], task['worker_started_at']):
            continue
        result = finish(store, evidence, outcome='reclaimed', event_kind='reconciled', error='orphaned running card (broken claim bookkeeping)', payload={'reason': 'orphaned_running', 'claim_lock': task['claim_lock'], 'claim_expires': task['claim_expires'], 'worker_pid': task['worker_pid'], 'now': int(time.time())}, comment="reconciliation: card was 'running' with no valid claim (dead/gone worker) — requeued to ready")
        if result is not None:
            reconciled.append(task['id'])
    return reconciled

def _elapsed(evidence, now):
    started = evidence.run.get('started_at')
    if started is None:
        started = evidence.task['started_at']
    return None if started is None else now - started

def enforce_max_runtime(store, *, signal_fn=None):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    now = int(time.time())
    timed_out = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        limit, elapsed = (task['max_runtime_seconds'], _elapsed(evidence, now))
        if limit is None or elapsed is None or elapsed < limit or (not task['worker_pid']):
            continue
        if not (task['claim_lock'] or '').startswith(kb._host_prefix()):
            continue
        if recovery.owner_reclaim_blocked(evidence, task['id']):
            continue
        termination = terminate(store, evidence, signal_fn, 'max_runtime_worker_alive')
        if termination is None:
            continue
        result = finish(store, evidence, outcome='timed_out', error=f'elapsed {elapsed}s > limit {limit}s', payload={'pid': task['worker_pid'], 'elapsed_seconds': elapsed, 'limit_seconds': limit, 'sigkill': termination.get('sigkill', False)}, charge=True)
        if result is not None:
            timed_out.append(task['id'])
    return timed_out

def detect_stale_running(store, *, stale_timeout_seconds=0, signal_fn=None):
    from hermes_cli import kanban_owner_recovery as recovery
    from hermes_cli.kanban_db_dispatch import _STALE_HEARTBEAT_GAP_SECONDS
    if stale_timeout_seconds <= 0:
        return []
    now = int(time.time())
    reclaimed = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        elapsed, heartbeat = (_elapsed(evidence, now), task['last_heartbeat_at'])
        age = None if heartbeat is None else now - heartbeat
        if elapsed is None or elapsed < stale_timeout_seconds or (age is not None and age < _STALE_HEARTBEAT_GAP_SECONDS):
            continue
        if recovery.owner_reclaim_blocked(evidence, task['id']):
            continue
        termination = terminate(store, evidence, signal_fn, 'heartbeat_stale_worker_alive')
        if termination is None:
            continue
        error = (f'no heartbeat for {age}s' if age is not None else 'no heartbeat ever') + f' after {elapsed}s running'
        result = finish(store, evidence, outcome='stale', error=error, payload={'elapsed_seconds': elapsed, 'last_heartbeat_at': heartbeat, 'heartbeat_age_seconds': age, 'timeout_seconds': stale_timeout_seconds, 'pid': task['worker_pid'], **termination})
        if result is not None:
            reclaimed.append(task['id'])
    return reclaimed

def finish(store, evidence, *, outcome, error, payload, charge=False, failure_limit=None, comment=None, run_metadata=None, event_kind=None):
    from hermes_cli import kanban_db as kb
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
            record_failure(conn, store, repo.require_task(conn, store, task_id), error, outcome=outcome, failure_limit=kb.DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit)
    return {'run_id': run_id, 'retry_status': retry}

def extend(store, evidence, now, *, termination=None, reason=None):
    from hermes_cli import kanban_db as kb
    task = evidence.task
    task_id = task['id']
    deferred = termination is not None
    expires = now + (kb.RECLAIM_DEFER_GRACE_SECONDS if deferred else kb._resolve_claim_ttl_seconds())
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

def terminate(store, evidence, signal_fn, reason):
    from hermes_cli import kanban_db as kb, kanban_owner_recovery as recovery
    task = evidence.task
    result = kb._terminate_reclaimed_worker(task['worker_pid'], task['claim_lock'], signal_fn=signal_fn, started_at=task['worker_started_at'])
    if kb._worker_survived_termination(result):
        extend(store, evidence, int(time.time()), termination=result, reason=reason)
        return None
    if recovery.owner_reclaim_blocked_after_kill(evidence, task['id'], signalled=bool(result.get('termination_attempted'))):
        return None
    return result

def _reap(store, run, signal_fn):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    pid, fingerprint = (run['worker_pid'], run['worker_started_at'])
    if pid == os.getpid() or not (run['claim_lock'] or '').startswith(kb._host_prefix()):
        return False
    if fingerprint == dispatch.UNVERIFIED_WORKER_FINGERPRINT and kb._pid_alive(pid):
        return False
    alive = kb._worker_alive(pid, fingerprint)
    termination = None
    if alive:
        termination = kb._terminate_reclaimed_worker(pid, run['claim_lock'], signal_fn=signal_fn, started_at=fingerprint)
        if not termination['terminated']:
            return False
    with store.write() as conn:
        if run_repo.get(conn, store, run['id']) != run:
            return False
        run_repo.update_run(conn, store, run['id'], worker_pid=None, worker_started_at=None)
        if alive:
            repo.event(conn, store, run['task_id'], 'terminal_worker_reaped', {'pid': pid, 'worker_started_at': fingerprint, **termination}, run['id'])
    return alive

def reap_terminal_workers(store, *, signal_fn=None):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    cutoff = int(time.time()) - dispatch.TERMINAL_WORKER_REAP_GRACE_SECONDS
    with store.read() as conn:
        rows = [repo.decode_record(row) for row in conn.execute(select(runs).where(repo.scope(runs, store), runs.c.ended_at <= cutoff, runs.c.worker_pid.is_not(None), runs.c.worker_started_at.is_not(None))).mappings()]
    reaped = []
    for run in rows:
        try:
            if _reap(store, run, signal_fn):
                reaped.append(run['task_id'])
        except (OSError, psutil.Error):
            kb._log.debug('kanban: terminal worker probe failed for run %s', run['id'], exc_info=True)
    return reaped

def replay_files(resource):
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        jobs = list(conn.scalars(select(file_jobs.c.board_id).where(file_jobs.c.store_id == owned, file_jobs.c.owner_home == encode_text(str(resource.scope.profile_home)), (file_jobs.c.state != 'done') | (file_jobs.c.action == 'import'))))
    for board_id in jobs:
        files.run_job(resource, board_id)
    _orphan_imports(resource)
    return len(jobs)

def _orphan_imports(resource):
    from hermes_db.domains.kanban.postgres.files import _remove_directory
    home = resource.scope.profile_home
    root = home / 'kanban' / 'imports'
    if not root.is_dir():
        return
    with files.local_files_lock(home):
        with resource.write() as conn:
            files.lock_files(conn, resource)
        with resource.read() as conn:
            live = {decode_text(value) for value in conn.scalars(select(file_jobs.c.stage_root).where(file_jobs.c.store_id == resource.scope.require_store_id(), file_jobs.c.stage_root.is_not(None)))}
        for stage in root.iterdir():
            if re.fullmatch('[0-9a-f]{32}', stage.name) and str(stage) not in live and owns_import_stage(resource, stage):
                _remove_directory(stage, parent=root)

def owns_import_stage(resource, stage):
    import json
    from hermes_db.integration.transfer.move_values import resource_key
    marker = stage / '.owner.json'
    if not marker.is_file() or marker.is_symlink():
        return False
    return json.loads(marker.read_text(encoding='utf-8-sig')) == dict(store_id=resource.scope.require_store_id(), home=str(resource.scope.profile_home), target=resource_key(resource._transactions))

def terminal_workspaces(resource):
    from hermes_db.domains.kanban.postgres.workspaces import cleanup_workspace
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        rows = list(conn.execute(select(tasks.c.board_id, kanban_boards.c.slug, tasks.c.id).join(kanban_boards, (tasks.c.store_id == kanban_boards.c.store_id) & (tasks.c.board_id == kanban_boards.c.board_id)).where(tasks.c.store_id == owned, tasks.c.status.in_((b'done', b'archived', b'failed', b'cancelled')), tasks.c.workspace_path.is_not(None), tasks.c.workspace_kind.in_((b'scratch', b'worktree')))))
    for board_id, slug, task_id in rows:
        with BoardResource(resource, board_id, slug) as board, board_files(board):
            cleanup_workspace(board, decode_text(task_id))
    return len(rows)

def pending_workspaces(resource):
    import json
    from hermes_db.tables.kanban_workspaces import paths
    from hermes_db.domains.kanban.postgres.workspaces import resume_pending
    with resource.read() as conn:
        pending = list(conn.execute(select(paths.c.path_key, paths.c.cleanup_token, paths.c.cleanup_payload).where(paths.c.store_id == resource.scope.require_store_id(), paths.c.cleanup_token.is_not(None))))
    if not pending:
        return
    with files.local_files_lock(resource.scope.profile_home):
        for path_key, token, raw in pending:
            if raw is None:
                from hermes_db.errors import StorageConfigurationError
                raise StorageConfigurationError('Workspace cleanup lacks a captured intent; retain files for explicit reconciliation')
            payload = json.loads(bytes(raw))
            with BoardResource(resource, payload['board_id'], payload['slug']) as board, board_files(board):
                resume_pending(board, payload['task'], decode_text(path_key), token)
