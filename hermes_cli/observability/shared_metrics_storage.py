"""Backend selection and SQLite-only named operations for metrics consumers."""

from hermes_cli.db_setup import storage_backend
from hermes_db.errors import StorageConfigurationError


def postgres_store(cls, database_path, outbox_directory, profile_home):
    from .shared_metrics import SharedMetricsStore
    from agent.runtime_domain_store import worker_resource
    worker = worker_resource('metrics', profile_home=profile_home) if cls is SharedMetricsStore else None
    if worker is not None:
        from hermes_db.domains.runtime.postgres.metrics import WorkerMetricsStore
        return WorkerMetricsStore(worker)
    if cls is SharedMetricsStore and storage_backend(profile_home) == "postgresql":
        from hermes_db.domains.metrics.postgres.store import PostgresMetricsStore
        from hermes_db.domains.metrics.api import capture_metrics
        return PostgresMetricsStore(capture_metrics(profile_home), outbox_directory=outbox_directory)
    return object.__new__(cls)


def assert_sqlite(home):
    if storage_backend(home) != "sqlite":
        raise StorageConfigurationError("Selected PG metrics cannot open a private SQLite connection")


def reconcile_sqlite(store, enabled, now):
    from .shared_metrics_sender import reconcile_send_consent
    with store._write() as connection:
        reconcile_send_consent(connection, enabled, now=now)


def consented_day_sqlite(store, start):
    with store._connection() as connection:
        return connection.execute("SELECT 1 FROM send_consent_windows WHERE closed_at IS NULL AND opened_at <= ? LIMIT 1", (start,)).fetchone() is not None
