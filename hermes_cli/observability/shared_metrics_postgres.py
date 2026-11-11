"""Captured PG metrics ownership, package files and transport assembly."""

from contextlib import contextmanager
from pathlib import Path
from datetime import timedelta
import json
import logging
from hermes_db.domains.metrics.api import MetricsRef
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.metrics.postgres.store import PostgresMetricsStore
from hermes_db.domains.metrics.postgres.sender import PostgresMetricsSender
from hermes_cli.observability.shared_metrics_export import MetricsExport, _ensure_private
from hermes_cli.observability.shared_metrics_transport import MetricsTransport
from hermes_db.domains.metrics import policy as native
from utils import atomic_json_write
logger = logging.getLogger("hermes_cli.observability.shared_metrics")

def capture_metrics(profile_home=None):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with acquire_profile_domain("metrics", profile_home=profile_home) as resource:
        return MetricsRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions))


@contextmanager
def open_metrics(reference, *, write=False):
    from hermes_db.domains.metrics.bound import BoundMetricsRef
    from hermes_db.domains.metrics.api import open_metrics as open_bound
    if isinstance(reference, BoundMetricsRef):
        with open_bound(reference, write=write) as value:
            yield value
        return
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    from hermes_db.domains.metrics.postgres.records import lock_store
    with _owning_profile(reference.profile_home), acquire_profile_domain("metrics", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured metrics backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured metrics database target changed; reopen its owning runtime")
        with (resource.write() if write else resource.read()) as conn:
            if write:
                lock_store(conn, resource)
            yield conn, resource


class OwnedPostgresMetricsStore(PostgresMetricsStore, MetricsExport):
    def __init__(self, reference, *, outbox_directory=None):
        super().__init__(reference, open_metrics=open_metrics)
        root = self.profile_home / "telemetry" / "shared_metrics"
        self.outbox_directory = Path(outbox_directory) if outbox_directory is not None else root / "postgresql" / "outbox"

    def create_and_export_package(self):
        self._prepare_export_package()
        return self._export_and_prune()

    def _export_pending_packages(self):
        rows = self._pending_exports()
        exported = []
        if rows:
            _ensure_private(self.outbox_directory, 0o700)
        for row in rows:
            path = self.outbox_directory / f"{row['package_id']}.json"
            atomic_json_write(path, json.loads(row["payload_json"]), indent=None, separators=(",", ":"), sort_keys=True, mode=0o600)
            self._mark_package_exported(row["package_id"])
            exported.append(path)
        return exported

    def _prune_expired_history(self, *, now=None):
        cutoff = native._isoformat((now or native._utc_now()) - timedelta(days=native._LOCAL_HISTORY_RETENTION_DAYS))
        ids = self._expired_packages(cutoff)
        removed = []
        for package_id in ids:
            try:
                (self.outbox_directory / f"{package_id}.json").unlink(missing_ok=True)
                removed.append(package_id)
            except OSError:
                logger.warning("Unable to prune expired shared-metrics package %s", package_id, exc_info=True)
        self._prune_packages(removed, cutoff)


class OwnedPostgresMetricsSender(PostgresMetricsSender, MetricsTransport):
    """Bind named SQL claims to the real application transport."""
