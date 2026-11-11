"""Kanban dispatch workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.errors import StorageConfigurationError, StorageError, StorageBusyError
import logging
from functools import partial
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

logger = logging.getLogger('hermes_cli.kanban_db')




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

    def release(self):
        with DomainResource.write(self.store) as conn:
            conn.execute(delete(leases).where(_key(self.store), leases.c.token == self.token))



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


def spawn_candidate(conn, store, claimed, lease):
    lease.validate(conn, lock=True)
    task = repo.get(conn, store, claimed.id)
    return task is not None and task['status'] == 'running' and task['current_run_id'] == claimed.current_run_id and task['claim_lock'] == claimed.claim_lock


def refresh_spawn_claim(conn, store, claimed, expires):
    repo.task_update(conn, store, claimed.id, claim_expires=expires)
    run_repo.update_run(conn, store, claimed.current_run_id, claim_expires=expires)


def respawn_candidate(conn, store, task_id):
    task = repo.get(conn, store, task_id)
    if task is None:
        return None, None
    latest = conn.execute(select(runs).where(repo.key(store, task_id, runs), runs.c.ended_at.is_not(None)).order_by(runs.c.ended_at.desc(), runs.c.id.desc()).limit(1)).mappings().one_or_none()
    return task, repo.decode_record(latest) if latest else None



def set_worker_fingerprint(store, task_id, pid, fingerprint, *, run_id=None, claim_lock=None):
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


def adoption_candidate(conn, store, task_id, run_id):
    task = repo.get(conn, store, task_id)
    if task is None or task['status'] != 'running' or task['current_run_id'] != int(run_id):
        return None
    return task


def register_adopted_worker(conn, store, task_id, run_id, pid, fingerprint):
    repo.task_update(conn, store, task_id, worker_pid=int(pid), worker_started_at=fingerprint)
    run_repo.update_run(conn, store, run_id, worker_pid=int(pid), worker_started_at=fingerprint)
    repo.event(conn, store, task_id, 'worker_registered', {'pid': int(pid), 'started_at': fingerprint}, int(run_id))
