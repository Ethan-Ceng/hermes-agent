"""Automatic ticks share existing orchestration under a renewable scoped PG lease."""

from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.kanban.postgres.operations.dispatch_lease import hold_dispatch_lease
from hermes_db.domains.kanban.postgres.operations.dispatch_permit import DispatchPermit


def dispatch_once(store, *, spawn_fn=None, ttl_seconds=None, dry_run=False, max_spawn=None,
                  max_in_progress=None, failure_limit=2, stale_timeout_seconds=0, board=None,
                  default_assignee=None, max_in_progress_per_profile=None, reconcile_orphans=True):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    if board is not None and board != store.slug:
        raise StorageConfigurationError("Dispatcher Board must match its owning resource")
    with hold_dispatch_lease(store) as lease:
        if lease is None:
            result = dispatch.DispatchResult(skipped_locked=True)
        else:
            permit = DispatchPermit(lease, max_spawn, max_in_progress)
            result = dispatch._dispatch_once_locked(store, spawn_fn=spawn_fn, ttl_seconds=ttl_seconds, dry_run=dry_run,
                max_spawn=max_spawn, max_in_progress=max_in_progress, failure_limit=failure_limit,
                stale_timeout_seconds=stale_timeout_seconds, board=store.slug, default_assignee=default_assignee,
                max_in_progress_per_profile=max_in_progress_per_profile, reconcile_orphans=reconcile_orphans,
                dispatch_permit=permit)
            lease.check()
    kb._fire_dispatch_tick_hook(result, board=store.slug, dry_run=dry_run)
    return result
