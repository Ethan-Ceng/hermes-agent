"""Application dispatcher, lease keepalive and process/workspace orchestration."""
import logging
import time
from functools import partial
from contextlib import contextmanager
from threading import Event
from hermes_db.errors import StorageConfigurationError, StorageError
from hermes_db.domains.kanban.postgres import dispatch as db
from hermes_cli.kanban_storage_claims import _claim
logger = logging.getLogger('hermes_cli.kanban_db')


class DispatchLease(db.DispatchLease):
    def __init__(self, store):
        super().__init__(store)
        self.stopping = Event()

    def _keep_alive(self):
        while not self.stopping.wait(db.RENEW_SECONDS):
            try:
                self.renew()
            except StorageError as error:
                self.error = error
                return


class DispatchPermit(db.DispatchPermit):
    def before_spawn(self, store, claimed, ttl_seconds):
        with store.write() as conn:
            if not db.spawn_candidate(conn, store, claimed, self.lease):
                return False
            expires = int(time.time()) + store.policy.resolve_claim_ttl_seconds(ttl_seconds)
            db.refresh_spawn_claim(conn, store, claimed, expires)
        return True



def dispatch_once(store, *, spawn_fn=None, ttl_seconds=None, dry_run=False, max_spawn=None, max_in_progress=None, failure_limit=2, stale_timeout_seconds=0, board=None, default_assignee=None, max_in_progress_per_profile=None, reconcile_orphans=True):

    if board is not None and board != store.slug:
        raise StorageConfigurationError('Dispatcher Board must match its owning resource')
    with hold_dispatch_lease(store) as lease:
        if lease is None:
            result = store.result_values.dispatch_result(skipped_locked=True)
        else:
            permit = DispatchPermit(lease, max_spawn, max_in_progress)
            result = store.processes.dispatch_once_locked(store, spawn_fn=spawn_fn, ttl_seconds=ttl_seconds, dry_run=dry_run, max_spawn=max_spawn, max_in_progress=max_in_progress, failure_limit=failure_limit, stale_timeout_seconds=stale_timeout_seconds, board=store.slug, default_assignee=default_assignee, max_in_progress_per_profile=max_in_progress_per_profile, reconcile_orphans=reconcile_orphans, dispatch_permit=permit)
            lease.check()
    store.observers.fire_dispatch_tick_hook(result, board=store.slug, dry_run=dry_run)
    return result


def _guard(store, task_id, assignee, result, lane, dry_run, cap, running):

    exists = store.processes.profile_exists_fn()
    if exists is not None and (not exists(assignee)):
        result.skipped_nonspawnable.append(task_id)
        if not dry_run:
            db.diagnostic(store, task_id, 'skipped_nonspawnable', {'assignee': assignee}, once=True)
        return False
    if cap is not None and running.get(assignee, 0) >= cap:
        result.skipped_per_profile_capped.append((task_id, assignee, running.get(assignee, 0)))
        return False
    reason = check_respawn_guard(store, task_id, lane=lane)
    if reason is not None:
        result.respawn_guarded.append((task_id, reason))
        if not dry_run:
            db.diagnostic(store, task_id, 'respawn_guarded', {'reason': reason})
        return False
    return True


def _workspace(store, claimed):
    if claimed.workspace_kind == 'worktree':
        path, branch = store.files.resolve_worktree_workspace(claimed, board=store.slug)
        store.set_branch_name(claimed.id, branch or (claimed.branch_name or '').strip() or f'wt/{claimed.id}')
    else:
        path = store.files.resolve_workspace(claimed, board=store.slug)
    from hermes_cli.kanban_storage_workspaces import set_workspace_path
    set_workspace_path(store, claimed.id, str(path))
    store.files.maybe_emit_scratch_tip(store, claimed.id, claimed.workspace_kind)
    return str(path)


def _spawn_failure(store, task, error, result, failure_limit, *, workspace=False):

    from tools.process_registry import RestartSafeScopeUnavailable
    infrastructure = isinstance(error, RestartSafeScopeUnavailable)
    message = f'workspace: {error}' if workspace else str(error)
    if store._record_task_failure(task.id, message, outcome='spawn_failed', failure_limit=failure_limit, release_claim=True, end_run=True, infrastructure=infrastructure, expected_run_id=task.current_run_id):
        result.auto_blocked.append(task.id)


def _dispatch_lane_task(store, row, assignee, result, *, lane, dry_run, ttl_seconds, board, failure_limit, spawn_fn, per_profile_cap, per_profile_running, dispatch_permit=None):

    if dispatch_permit is None:
        raise StorageConfigurationError('Automatic Kanban claims require a dispatch lease')
    task_id = row['id']
    dispatch_permit.lease.check()
    if not _guard(store, task_id, assignee, result, lane, dry_run, per_profile_cap, per_profile_running):
        return False
    if dry_run:
        result.spawned.append((task_id, assignee, ''))
    else:
        permit = dispatch_permit.for_assignee(assignee, per_profile_cap)
        task = _claim(store, task_id, lane, ttl_seconds, None, dispatch_permit=permit)
        if task is None:
            return False
        try:
            workspace = _workspace(store, task)
        except StorageError:
            raise
        except Exception as error:
            logger.exception('kanban: workspace preparation failed for task %s', task.id)
            _spawn_failure(store, task, error, result, failure_limit, workspace=True)
            return False
        if lane == 'review':
            task.skills = list(dict.fromkeys([*(task.skills or []), 'sdlc-review']))
        if not permit.before_spawn(store, task, ttl_seconds):
            return False
        try:
            spawn = spawn_fn or partial(store.processes.default_spawn, board_owner=store.codec.board_reference(store))
            pid = store.processes.call_spawn_fn(spawn, task, workspace, store.slug)
        except StorageError:
            raise
        except Exception as error:
            logger.exception('kanban: worker spawn failed for task %s', task.id)
            _spawn_failure(store, task, error, result, failure_limit)
            return False
        if pid:
            _set_worker_pid(store, task.id, int(pid), run_id=task.current_run_id, claim_lock=task.claim_lock)
        store.observers.fire_worker_spawned_hook(store, task, workspace, pid, board=store.slug)
        result.spawned.append((task.id, task.assignee or '', workspace))
    if per_profile_cap is not None and assignee:
        per_profile_running[assignee] = per_profile_running.get(assignee, 0) + 1
    return True


def _finish_tick(lease, thread):
    lease.stopping.set()
    thread.join()
    lease.release()


@contextmanager
def hold_dispatch_lease(store):
    from agent.memory_provider import spawn_context_thread
    lease = DispatchLease(store)
    if not lease.acquire():
        yield None
        return
    thread = spawn_context_thread(lease._keep_alive, name='kanban-dispatch-lease', daemon=True)
    thread.start()
    try:
        yield lease
    except BaseException as primary:
        try:
            _finish_tick(lease, thread)
        except StorageError as cleanup:
            primary.add_note(f'Dispatch lease release failed ({type(cleanup).__name__}); ownership expires by database time')
        raise
    else:
        _finish_tick(lease, thread)


def _has_spawnable(store, status):

    rows = db._lane_rows(store, status)
    exists = store.processes.profile_exists_fn()
    return any(row['assignee'] is not None and (exists is None or exists(row['assignee'])) for row in rows)


def check_respawn_guard(store, task_id, *, lane='ready'):
    now = int(time.time())
    with store.read() as conn:
        task, latest = db.respawn_candidate(conn, store, task_id)
        if task is None:
            return None
        handled, reason = store.policy.respawn_primary_guard(task['last_failure_error'], latest, lane, now)
        if handled:
            return reason
        history = db._guard_history(conn, store, task_id, now)
    return store.policy.respawn_history_guard(*history)


def _set_worker_pid(store, task_id, pid, *, run_id=None, claim_lock=None):

    from hermes_db.domains.kanban.rules import UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = store.processes.process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    return db.set_worker_fingerprint(store, task_id, pid, fingerprint, run_id=run_id, claim_lock=claim_lock)


def adopt_worker_pid(store, task_id, run_id, pid):


    from hermes_db.domains.kanban.rules import UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = store.processes.process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    with store.write() as conn:
        task = db.adoption_candidate(conn, store, task_id, run_id)
        if task is None:
            return False
        if task['worker_pid'] is None and (task['claim_lock'] or '').startswith(store.processes.host_prefix()):
            db.register_adopted_worker(conn, store, task_id, run_id, pid, fingerprint)
    return True
