"""Application worker recovery and file/workspace reconciliation."""
import logging
import os
import re
import time
import psutil
from collections import Counter
from hermes_db.domains.kanban import rules as _storage_shared_1, rules as _storage_shared_1_, rules as _storage_shared_1__
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.domains.kanban.postgres import maintenance as db, evidence as evidence_repo
from hermes_cli import kanban_storage_files as files
from hermes_db.core.values import decode_text
_kanban_logger = logging.getLogger('hermes_cli.kanban_db')



def _prepare(store, board):

    prepared = []
    now = time.time()
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if not task['worker_pid'] or not (task['claim_lock'] or '').startswith(store.processes.host_prefix()):
            continue
        started = task['started_at']
        if started is not None and now - started < store.policy.resolve_crash_grace_seconds():
            continue
        if store.processes.worker_alive(task['worker_pid'], task['worker_started_at']):
            continue
        if store.processes.owner_reclaim_blocked(evidence, task['id'], crash_sweep=True):
            continue
        code = store.processes.managed_run_exit_code(evidence, task['id'], task['worker_pid'], task['claim_lock'])
        dead = store.processes.classify_dead_worker(task['worker_pid'], task['claim_lock'], code, task_id=task['id'], board=board)
        store.processes.apply_attempt_note(evidence, task['id'], task['worker_pid'], dead)
        prepared.append((evidence, dead))
    return prepared


def detect_crashed_workers(store, board=None):

    prepared = _prepare(store, store.slug if board is None else board)
    crashed, limited, blocked, hooks = ([], [], [], [])
    if prepared:
        with store.write() as conn:
            accepted = [(evidence, dead) for evidence, dead in prepared if evidence_repo.unchanged(conn, store, evidence)]
            frequencies = Counter((_storage_shared_1__._error_fingerprint(dead.error_text) for _, dead in accepted if not dead.rate_limited))
            for evidence, dead in accepted:
                tripped, hook = db._close(conn, store, evidence, dead, frequencies)
                (limited if dead.rate_limited else crashed).append(evidence.task['id'])
                if tripped:
                    blocked.append(evidence.task['id'])
                hooks.append(hook)
    store.processes.record_crash_summary(blocked, limited)
    if store.observers.kanban_observer_consumed('on_kanban_worker_exited'):
        for hook in hooks:
            store.observers.fire_kanban_lifecycle_hook('on_kanban_worker_exited', hook.pop('task_id'), board=store.slug, **hook)
    return crashed


def release_stale_claims(store, *, signal_fn=None, failure_limit=None):

    now = int(time.time())
    reclaimed = 0
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        expires = task['claim_expires']
        if expires is None or expires >= now or store.processes.owner_reclaim_blocked(evidence, task['id']):
            continue
        local = (task['claim_lock'] or '').startswith(store.processes.host_prefix())
        heartbeat = task['last_heartbeat_at']
        stale = heartbeat is not None and now - heartbeat > _storage_shared_1.DEFAULT_CLAIM_HEARTBEAT_MAX_STALE_SECONDS
        if local and task['worker_pid'] and store.processes.worker_alive(task['worker_pid'], task['worker_started_at']) and (not stale):
            extend(store, evidence, now)
            continue
        termination = terminate(store, evidence, signal_fn, 'ttl_expired_worker_alive')
        if termination is None:
            continue
        payload = {'stale_lock': task['claim_lock'], 'worker_pid': task['worker_pid'], 'claim_expires': expires, 'last_heartbeat_at': heartbeat, 'now': now, 'host_local': local, 'heartbeat_stale': stale, **termination}
        result = db.finish(store, evidence, outcome='reclaimed', error=store.processes.reclaim_error(evidence, task['id'], task['claim_lock']), payload=payload, run_metadata=termination, charge=True, failure_limit=failure_limit)
        if result is None:
            continue
        reclaimed += 1
        if store.observers.kanban_observer_consumed('on_kanban_worker_stale_claim'):
            store.observers.fire_kanban_lifecycle_hook('on_kanban_worker_stale_claim', task['id'], board=store.slug, assignee=task['assignee'], run_id=result['run_id'], worker_pid=task['worker_pid'], heartbeat_stale=stale, retry_status=result['retry_status'])
    return reclaimed


def reconcile_orphaned_running(store):

    reconciled = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        if task['claim_lock'] is not None and task['claim_expires'] is not None:
            continue
        if store.processes.owner_reclaim_blocked(evidence, task['id']):
            continue
        if task['worker_pid'] and store.processes.worker_alive(task['worker_pid'], task['worker_started_at']):
            continue
        result = db.finish(store, evidence, outcome='reclaimed', event_kind='reconciled', error='orphaned running card (broken claim bookkeeping)', payload={'reason': 'orphaned_running', 'claim_lock': task['claim_lock'], 'claim_expires': task['claim_expires'], 'worker_pid': task['worker_pid'], 'now': int(time.time())}, comment="reconciliation: card was 'running' with no valid claim (dead/gone worker) — requeued to ready")
        if result is not None:
            reconciled.append(task['id'])
    return reconciled


def enforce_max_runtime(store, *, signal_fn=None):

    now = int(time.time())
    timed_out = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        limit, elapsed = (task['max_runtime_seconds'], db._elapsed(evidence, now))
        if limit is None or elapsed is None or elapsed < limit or (not task['worker_pid']):
            continue
        if not (task['claim_lock'] or '').startswith(store.processes.host_prefix()):
            continue
        if store.processes.owner_reclaim_blocked(evidence, task['id']):
            continue
        termination = terminate(store, evidence, signal_fn, 'max_runtime_worker_alive')
        if termination is None:
            continue
        result = db.finish(store, evidence, outcome='timed_out', error=f'elapsed {elapsed}s > limit {limit}s', payload={'pid': task['worker_pid'], 'elapsed_seconds': elapsed, 'limit_seconds': limit, 'sigkill': termination.get('sigkill', False)}, charge=True)
        if result is not None:
            timed_out.append(task['id'])
    return timed_out


def detect_stale_running(store, *, stale_timeout_seconds=0, signal_fn=None):

    from hermes_db.domains.kanban.rules import _STALE_HEARTBEAT_GAP_SECONDS
    if stale_timeout_seconds <= 0:
        return []
    now = int(time.time())
    reclaimed = []
    for evidence in evidence_repo.running_snapshots(store):
        task = evidence.task
        elapsed, heartbeat = (db._elapsed(evidence, now), task['last_heartbeat_at'])
        age = None if heartbeat is None else now - heartbeat
        if elapsed is None or elapsed < stale_timeout_seconds or (age is not None and age < _STALE_HEARTBEAT_GAP_SECONDS):
            continue
        if store.processes.owner_reclaim_blocked(evidence, task['id']):
            continue
        termination = terminate(store, evidence, signal_fn, 'heartbeat_stale_worker_alive')
        if termination is None:
            continue
        error = (f'no heartbeat for {age}s' if age is not None else 'no heartbeat ever') + f' after {elapsed}s running'
        result = db.finish(store, evidence, outcome='stale', error=error, payload={'elapsed_seconds': elapsed, 'last_heartbeat_at': heartbeat, 'heartbeat_age_seconds': age, 'timeout_seconds': stale_timeout_seconds, 'pid': task['worker_pid'], **termination})
        if result is not None:
            reclaimed.append(task['id'])
    return reclaimed


def extend(store, evidence, now, *, termination=None, reason=None):

    deferred = termination is not None
    expires = now + (_storage_shared_1.RECLAIM_DEFER_GRACE_SECONDS if deferred else store.policy.resolve_claim_ttl_seconds())
    return db.extend_claim(store, evidence, now, expires, termination=termination, reason=reason)


def terminate(store, evidence, signal_fn, reason):

    task = evidence.task
    result = store.processes.terminate_reclaimed_worker(task['worker_pid'], task['claim_lock'], signal_fn=signal_fn, started_at=task['worker_started_at'])
    if store.processes.worker_survived_termination(result):
        extend(store, evidence, int(time.time()), termination=result, reason=reason)
        return None
    if store.processes.owner_reclaim_blocked_after_kill(evidence, task['id'], signalled=bool(result.get('termination_attempted'))):
        return None
    return result


def _reap(store, run, signal_fn):

    pid, fingerprint = (run['worker_pid'], run['worker_started_at'])
    if pid == os.getpid() or not (run['claim_lock'] or '').startswith(store.processes.host_prefix()):
        return False
    if fingerprint == _storage_shared_1__.UNVERIFIED_WORKER_FINGERPRINT and store.processes.pid_alive(pid):
        return False
    alive = store.processes.worker_alive(pid, fingerprint)
    termination = None
    if alive:
        termination = store.processes.terminate_reclaimed_worker(pid, run['claim_lock'], signal_fn=signal_fn, started_at=fingerprint)
        if not termination['terminated']:
            return False
    return db.reap_terminal_claim(store, run, alive, termination, pid, fingerprint)


def reap_terminal_workers(store, *, signal_fn=None):

    cutoff = int(time.time()) - _storage_shared_1__.TERMINAL_WORKER_REAP_GRACE_SECONDS
    rows = db.terminal_worker_rows(store, cutoff)
    reaped = []
    for run in rows:
        try:
            if _reap(store, run, signal_fn):
                reaped.append(run['task_id'])
        except (OSError, psutil.Error):
            _kanban_logger.debug('kanban: terminal worker probe failed for run %s', run['id'], exc_info=True)
    return reaped


def replay_files(resource):
    jobs = db.pending_file_boards(resource)
    for board_id in jobs:
        files.run_job(resource, board_id)
    _orphan_imports(resource)
    return len(jobs)


def _orphan_imports(resource):
    from hermes_cli.kanban_storage_files import _remove_directory
    home = resource.scope.profile_home
    root = home / 'kanban' / 'imports'
    if not root.is_dir():
        return
    with files.local_files_lock(home):
        live = db.live_import_stages(resource)
        for stage in root.iterdir():
            if re.fullmatch('[0-9a-f]{32}', stage.name) and str(stage) not in live and owns_import_stage(resource, stage):
                _remove_directory(stage, parent=root)


def owns_import_stage(resource, stage):
    import json
    from hermes_db.core.values import resource_key
    marker = stage / '.owner.json'
    if not marker.is_file() or marker.is_symlink():
        return False
    return json.loads(marker.read_text(encoding='utf-8-sig')) == dict(store_id=resource.scope.require_store_id(), home=str(resource.scope.profile_home), target=resource_key(resource._transactions))


def terminal_workspaces(resource):
    from hermes_cli.kanban_storage_workspaces import cleanup_workspace
    rows = db.terminal_workspace_rows(resource)
    for board_id, slug, task_id in rows:
        with BoardResource(resource, board_id, slug) as board, board._operation_scope():
            cleanup_workspace(board, decode_text(task_id))
    return len(rows)


def pending_workspaces(resource):
    import json
    from hermes_cli.kanban_storage_workspaces import resume_pending
    pending = db.pending_workspace_rows(resource)
    if not pending:
        return
    with files.local_files_lock(resource.scope.profile_home):
        for path_key, token, raw in pending:
            if raw is None:
                from hermes_db.errors import StorageConfigurationError
                raise StorageConfigurationError('Workspace cleanup lacks a captured intent; retain files for explicit reconciliation')
            payload = json.loads(bytes(raw))
            with BoardResource(resource, payload['board_id'], payload['slug']) as board, board._operation_scope():
                resume_pending(board, payload['task'], decode_text(path_key), token)
