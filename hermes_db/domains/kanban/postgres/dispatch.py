"""Kanban dispatch workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.errors import StorageConfigurationError, StorageError, StorageBusyError
import logging
from functools import partial
from hermes_db.domains.kanban.postgres.claims import _claim
from contextlib import contextmanager
from threading import Event
import uuid
from sqlalchemy import BigInteger, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.resource import DomainResource
from hermes_db.tables.kanban_dispatch import dispatch_leases as leases
from dataclasses import dataclass, replace
import time
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo
from hermes_db.tables.kanban import tasks, comments, events, runs
from hermes_db.core.values import encode_text, decode_text

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
logger = logging.getLogger('hermes_cli.kanban_db')

def _guard(store, task_id, assignee, result, lane, dry_run, cap, running):

    exists = store.processes.profile_exists_fn()
    if exists is not None and (not exists(assignee)):
        result.skipped_nonspawnable.append(task_id)
        if not dry_run:
            diagnostic(store, task_id, 'skipped_nonspawnable', {'assignee': assignee}, once=True)
        return False
    if cap is not None and running.get(assignee, 0) >= cap:
        result.skipped_per_profile_capped.append((task_id, assignee, running.get(assignee, 0)))
        return False
    reason = store.check_respawn_guard(task_id, lane=lane)
    if reason is not None:
        result.respawn_guarded.append((task_id, reason))
        if not dry_run:
            diagnostic(store, task_id, 'respawn_guarded', {'reason': reason})
        return False
    return True

def _workspace(store, claimed):
    if claimed.workspace_kind == 'worktree':
        path, branch = store.files.resolve_worktree_workspace(claimed, board=store.slug)
        store.set_branch_name(claimed.id, branch or (claimed.branch_name or '').strip() or f'wt/{claimed.id}')
    else:
        path = store.files.resolve_workspace(claimed, board=store.slug)
    store.set_workspace_path(claimed.id, str(path))
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
            store._set_worker_pid(task.id, int(pid), run_id=task.current_run_id, claim_lock=task.claim_lock)
        store.observers.fire_worker_spawned_hook(store, task, workspace, pid, board=store.slug)
        result.spawned.append((task.id, task.assignee or '', workspace))
    if per_profile_cap is not None and assignee:
        per_profile_running[assignee] = per_profile_running.get(assignee, 0) + 1
    return True
LEASE_SECONDS = 60
RENEW_SECONDS = 10

def _now():
    return cast(func.extract('epoch', func.clock_timestamp()), BigInteger)

def _key(store):
    return leases.c.store_id == store.scope.require_store_id()

class DispatchLease:

    def __init__(self, store):
        self.store = store
        self.token = uuid.uuid4().hex
        self.stopping = Event()
        self.error = None

    def acquire(self):
        with DomainResource.write(self.store) as conn:
            statement = insert(leases).values(store_id=self.store.scope.require_store_id(), token=self.token, lease_until=_now() + LEASE_SECONDS)
            return conn.scalar(statement.on_conflict_do_update(index_elements=[leases.c.store_id], set_={'token': self.token, 'lease_until': _now() + LEASE_SECONDS}, where=leases.c.lease_until <= _now()).returning(leases.c.token)) == self.token

    def validate(self, conn, *, lock=False):
        if self.error is not None:
            raise self.error
        statement = select(leases.c.token).where(_key(self.store), leases.c.lease_until > _now())
        if lock:
            statement = statement.with_for_update()
        if conn.scalar(statement) != self.token:
            raise StorageBusyError('Kanban dispatch lease expired or was replaced; no new worker may start')

    def check(self):
        with self.store.read() as conn:
            self.validate(conn)

    def renew(self):
        with DomainResource.write(self.store) as conn:
            changed = conn.execute(update(leases).where(_key(self.store), leases.c.token == self.token, leases.c.lease_until > _now()).values(lease_until=_now() + LEASE_SECONDS)).rowcount
            if changed != 1:
                raise StorageBusyError('Kanban dispatch lease was lost during a tick')

    def _keep_alive(self):
        while not self.stopping.wait(RENEW_SECONDS):
            try:
                self.renew()
            except StorageError as error:
                self.error = error
                return

    def release(self):
        with DomainResource.write(self.store) as conn:
            conn.execute(delete(leases).where(_key(self.store), leases.c.token == self.token))

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

@dataclass(frozen=True)
class DispatchPermit:
    lease: object
    max_spawn: int | None
    max_in_progress: int | None
    per_profile_cap: int | None = None
    assignee: str | None = None

    def for_assignee(self, assignee, cap):
        return replace(self, assignee=assignee, per_profile_cap=cap)

    def admit(self, conn, store, task):
        if self.lease.store.scope != store.scope:
            raise StorageConfigurationError('Dispatch lease belongs to another Profile store')
        self.lease.validate(conn, lock=True)
        if task['assignee'] != self.assignee:
            return False
        counts = select(func.count()).select_from(tasks).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.status == b'running')
        if self.max_in_progress is not None and conn.scalar(counts) >= self.max_in_progress:
            return False
        board_counts = counts.where(tasks.c.board_id == store.board_id)
        if self.max_spawn is not None and conn.scalar(board_counts) >= self.max_spawn:
            return False
        if self.per_profile_cap is not None:
            return conn.scalar(board_counts.where(tasks.c.assignee == encode_text(self.assignee))) < self.per_profile_cap
        return True

    def before_spawn(self, store, claimed, ttl_seconds):

        with store.write() as conn:
            self.lease.validate(conn, lock=True)
            task = repo.get(conn, store, claimed.id)
            if task is None or task['status'] != 'running' or task['current_run_id'] != claimed.current_run_id or (task['claim_lock'] != claimed.claim_lock):
                return False
            expires = int(time.time()) + store.policy.resolve_claim_ttl_seconds(ttl_seconds)
            repo.task_update(conn, store, claimed.id, claim_expires=expires)
            run_repo.update_run(conn, store, claimed.current_run_id, claim_expires=expires)
        return True

def _running_per_profile(store):
    with store.read() as conn:
        return {decode_text(row.assignee): int(row.n) for row in conn.execute(select(tasks.c.assignee, func.count().label('n')).where(repo.scope(tasks, store), tasks.c.status == b'running', tasks.c.assignee.is_not(None)).group_by(tasks.c.assignee))}

def count_running_tasks(store):
    with store.read() as conn:
        return conn.scalar(select(func.count()).select_from(tasks).where(repo.scope(tasks, store), tasks.c.status == b'running'))

def _count_other_running(store, board=None):
    with store.read() as conn:
        return conn.scalar(select(func.count()).select_from(tasks).where(tasks.c.store_id == store.scope.require_store_id(), tasks.c.board_id != store.board_id, tasks.c.status == b'running'))

def _lane_rows(store, status):
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(select(tasks.c.id, tasks.c.assignee).where(repo.scope(tasks, store), tasks.c.status == status.encode(), tasks.c.claim_lock.is_(None)).order_by(tasks.c.priority.desc(), tasks.c.created_at.asc().nulls_first(), tasks.c.id)).mappings()]

def _has_spawnable(store, status):

    rows = _lane_rows(store, status)
    exists = store.processes.profile_exists_fn()
    return any(row['assignee'] is not None and (exists is None or exists(row['assignee'])) for row in rows)

def _apply_default_assignee(store, task_id, assignee, *, dry_run):
    if dry_run:
        return True
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task['status'] != 'ready' or task['claim_lock'] is not None:
            return False
        if task['assignee']:
            return task['assignee'] == assignee
        repo.task_update(conn, store, task_id, assignee=assignee)
        repo.event(conn, store, task_id, 'assigned', {'assignee': assignee, 'source': 'kanban.default_assignee'})
    return True

def diagnostic(store, task_id, kind, payload, *, once=False):
    with store.write() as conn:
        if repo.get(conn, store, task_id) is None:
            return
        if once:
            history = repo.history(conn, store, task_id)
            if history and history[0]['kind'] == kind and (history[0]['payload'] == payload):
                return
        repo.event(conn, store, task_id, kind, payload)

def _guard_history(conn, store, task_id, now):

    success_cutoff = now - _storage_shared_1._RESPAWN_GUARD_SUCCESS_WINDOW
    pr_cutoff = now - _storage_shared_1._RESPAWN_GUARD_PR_WINDOW
    successes = [(row.ended_at, {}) for row in conn.execute(select(runs.c.ended_at).where(repo.key(store, task_id, runs), runs.c.outcome == b'completed', runs.c.ended_at >= success_cutoff))]
    event_rows = [(row['created_at'], repo.decode_record(row)) for row in conn.execute(select(events).where(repo.key(store, task_id, events), events.c.created_at >= min(success_cutoff, pr_cutoff))).mappings()]
    comment_rows = [(row['created_at'], repo.decode_record(row)) for row in conn.execute(select(comments).where(repo.key(store, task_id, comments), comments.c.created_at >= pr_cutoff)).mappings()]
    return (successes, event_rows, comment_rows)

def check_respawn_guard(store, task_id, *, lane='ready'):
    now = int(time.time())
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return None
        latest = conn.execute(select(runs).where(repo.key(store, task_id, runs), runs.c.ended_at.is_not(None)).order_by(runs.c.ended_at.desc(), runs.c.id.desc()).limit(1)).mappings().one_or_none()
        handled, reason = store.policy.respawn_primary_guard(task['last_failure_error'], repo.decode_record(latest) if latest else None, lane, now)
        if handled:
            return reason
        history = _guard_history(conn, store, task_id, now)
    return store.policy.respawn_history_guard(*history)

def _set_worker_pid(store, task_id, pid, *, run_id=None, claim_lock=None):

    from hermes_db.domains.kanban.rules import UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = store.processes.process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return
        run_id = task['current_run_id'] if run_id is None else run_id
        condition = repo.key(store, task_id) & (tasks.c.status == b'running') & tasks.c.worker_pid.is_(None)
        condition &= tasks.c.current_run_id.is_not_distinct_from(run_id)
        if claim_lock is not None:
            condition &= tasks.c.claim_lock == encode_text(claim_lock)
        changed = conn.execute(update(tasks).where(condition).values(worker_pid=int(pid), worker_started_at=encode_text(fingerprint))).rowcount
        if changed and run_id is not None:
            run_repo.update_run(conn, store, run_id, worker_pid=int(pid), worker_started_at=fingerprint)
        repo.event(conn, store, task_id, 'spawned', {'pid': int(pid), 'started_at': fingerprint}, run_id)

def adopt_worker_pid(store, task_id, run_id, pid):


    from hermes_db.domains.kanban.rules import UNVERIFIED_WORKER_FINGERPRINT
    fingerprint = store.processes.process_fingerprint(int(pid)) or UNVERIFIED_WORKER_FINGERPRINT
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task['status'] != 'running' or task['current_run_id'] != int(run_id):
            return False
        if task['worker_pid'] is None and (task['claim_lock'] or '').startswith(store.processes.host_prefix()):
            repo.task_update(conn, store, task_id, worker_pid=int(pid), worker_started_at=fingerprint)
            run_repo.update_run(conn, store, run_id, worker_pid=int(pid), worker_started_at=fingerprint)
            repo.event(conn, store, task_id, 'worker_registered', {'pid': int(pid), 'started_at': fingerprint}, int(run_id))
    return True
