"""A checked compute-only metrics barrier before the canonical execution is retired."""

import sys
from pathlib import Path

from agent.runtime_domain_store import owner_binding
from agent.runtime_session_store import WorkerPersistenceError


def quiesce(store):
    from hermes_db.scope import DatabaseScope, bind_profile_home
    binding = owner_binding(store)
    if binding['backend'] != 'postgresql':
        return
    with bind_profile_home(DatabaseScope(Path(binding['profile_home']), binding['store_id'])):
        _quiesce_pg(store)


def _quiesce_pg(store):
    module = sys.modules.get('hermes_cli.observability.relay_shared_metrics')
    runtime = None if module is None else module._RUNTIMES.get(module.relay_runtime.current_profile_key())
    if module is not None and module.enabled() and not isinstance(runtime, module._Runtime):
        raise WorkerPersistenceError('worker_metrics_runtime_unavailable')
    if module is not None and isinstance(runtime, module._Runtime):
        close_runtime(runtime)
    else:
        from hermes_db.domains.runtime.postgres.capabilities.worker_metrics_store import WorkerMetricsStore
        WorkerMetricsStore().create_and_export_package_if_due()
    store.flush_token_counts()


def close_runtime(runtime):
    # Don't hold a store, SDK or runtime lock while a subscriber waits for its owner receipt.
    with runtime._owner_scope():
        with runtime._sessions_lock:
            runtime._active = False
            sessions = list(runtime._sessions)
        for session_id in sessions:
            runtime.close_session({'session_id': session_id})
        with runtime._lineage_lock:
            unseen = list(runtime._lineage_of)
        for session_id in unseen:
            runtime._close_unseen_segment(session_id)
        with runtime._flush_lock:
            thread = runtime._flush_thread
        if thread is not None:
            thread.join(timeout=20)
            if thread.is_alive():
                raise WorkerPersistenceError('worker_metrics_flush_timeout')
        runtime.relay.subscribers.flush()
        runtime.subscriber.store.create_and_export_package_if_due()
        runtime.subscriber.deactivate()
        if runtime._registered:
            runtime.relay.subscribers.deregister(runtime._subscriber_name)
            runtime.host.release_managed_execution(runtime._subscriber_name)
            runtime._registered = False
        runtime._release()
