"""Post-receipt owner maintenance; no worker connection survives into file or HTTP work."""

from hermes_cli.db_setup import _owning_profile
from hermes_db.domains.metrics.bound import bound_store


def maintain(db):
    from hermes_cli.observability.relay_shared_metrics import _get_runtime, _resolved_send_config
    from hermes_db.domains.runtime.postgres.operations.worker_metrics_engagement import drain
    with _owning_profile(db.scope.profile_home):
        store = bound_store(db.scope, db._transactions)
        resolved = _resolved_send_config()
        store.reconcile_send_consent(resolved.send)
        drain(store)
        if not resolved.enabled:
            return
        store.create_and_export_package_if_due()
        # Owner send gates, current consent and the existing sender thread remain authoritative.
        if resolved.send:
            runtime = _get_runtime()
            if runtime is None:
                raise RuntimeError('owner_metrics_runtime_unavailable')
            runtime._send_exported_packages()
