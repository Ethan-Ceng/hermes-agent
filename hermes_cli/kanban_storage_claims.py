"""Application claimant policy, process reclamation and post-commit claim effects."""
import time
from hermes_cli.kanban_storage_effects import after_commit


def _claim(store, task_id, source, ttl_seconds, claimer, *, dispatch_permit=None):
    from hermes_db.domains.kanban.postgres import claims as db
    now = int(time.time())
    lock, expires = (claimer or store.processes.claimer_id(), now + store.policy.resolve_claim_ttl_seconds(ttl_seconds))
    claimed, effect_id = db.claim_prepared(store, task_id, source, now, lock, expires, dispatch_permit=dispatch_permit)
    if claimed is None:
        return None
    if source == 'ready':
        after_commit(store, effect_id)
    return claimed


def claim_task(store, task_id, *, ttl_seconds=None, claimer=None):
    return _claim(store, task_id, 'ready', ttl_seconds, claimer)


def claim_review_task(store, task_id, *, ttl_seconds=None, claimer=None):
    return _claim(store, task_id, 'review', ttl_seconds, claimer)


def heartbeat_claim(store, task_id, *, ttl_seconds=None, claimer=None):
    from hermes_db.domains.kanban.postgres import claims as db
    lock = claimer or store.processes.claimer_id()
    expires = int(time.time()) + store.policy.resolve_claim_ttl_seconds(ttl_seconds)
    return db.heartbeat_prepared(store, task_id, lock, expires)


def reclaim_task(store, task_id, *, reason=None, signal_fn=None):
    from hermes_db.domains.kanban.postgres import claims as db
    snapshot = db.reclaim_snapshot(store, task_id)
    if snapshot is None or (snapshot['status'] != 'running' and snapshot['claim_lock'] is None):
        return False
    termination = store.processes.terminate_reclaimed_worker(snapshot['worker_pid'], snapshot['claim_lock'], signal_fn=signal_fn, started_at=snapshot['worker_started_at'])
    return db.reclaim_prepared(store, task_id, snapshot, termination, reason=reason)


def block_task(store, task_id, *, reason=None, kind=None, expected_run_id=None):
    from hermes_db.domains.kanban.postgres import claims as db
    value, effect_id = db.block_prepared(store, task_id, reason=reason, kind=kind, expected_run_id=expected_run_id)
    if effect_id is not None:
        after_commit(store, effect_id)
    return value
