"""Selected PG metrics store; native code supplies only pure contracts and formatting."""

from datetime import timedelta
from hermes_db.domains.metrics import policy as native
from hermes_db.domains.metrics.policy import MetricsPolicy
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.metrics.postgres import records, outbox
from hermes_db.tables.metrics import packages


class PostgresMetricsStore(MetricsPolicy):
    backend = "postgresql"

    def __init__(self, reference, *, open_metrics):
        self.reference = reference
        self._open_metrics = open_metrics
        self.profile_home = self.reference.profile_home
        # The legacy SQLite path is never used to infer a Profile or opened in PG.
        self.database_path = None

    def _connection(self, **kwargs):
        raise StorageConfigurationError("PG metrics expose named operations, not a SQLite connection")

    def _write(self, **kwargs):
        raise StorageConfigurationError("PG metrics expose named operations, not a SQLite write transaction")

    def _record_once_per_interval(self, state_key, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        with self._open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now(), interval=True)

    def _record_once_ever(self, state_key, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        with self._open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now())

    def install_snapshot_due(self):
        with self._open_metrics(self.reference) as (conn, store):
            previous = self._parse_state_timestamp(records.get_state(conn, store, native._INSTALL_SNAPSHOT_STATE_KEY))
        now = native._utc_now()
        return previous is None or previous > now or now >= previous + timedelta(hours=24)

    def record_counter(self, metric_name, dimensions, resource, amount=1):
        self._validate_counter(metric_name, dimensions, resource)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1 or (amount != 1 and metric_name not in native.SUM_METRICS):
            raise ValueError(f"Unsupported amount for shared metric: {metric_name}")
        with self._open_metrics(self.reference, write=True) as (conn, store):
            records.record(conn, store, metric_name, dimensions, resource, native._utc_now(), amount)

    def record_counter_once_per_day(self, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        state_key = f"{native._DAILY_ONCE_STATE_PREFIX}{metric_name}:" + native._compact_json({key: value for key, value in dimensions.items() if key != "surface"})
        with self._open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now(), daily=True)

    def update_rollup_state(self, state_key, update):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            records.rollup(conn, store, state_key, update)

    def _latched(self, prefix):
        with self._open_metrics(self.reference) as (conn, store):
            return records.latched(conn, store, prefix)

    def counter_snapshot(self):
        with self._open_metrics(self.reference) as (conn, store):
            return records.snapshot(conn, store)

    def drain_deferred(self, busy_timeout_ms=5_000):
        # PG operations commit synchronously or raise; none are queued in memory.
        return None


    def _create_pending_packages_if_due(self):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            outbox.create_pending(conn, store, native._utc_now(), due=True)

    def _create_package(self):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            return outbox.create_one(conn, store, native._utc_now())



    def reconcile_send_consent(self, send_enabled, *, now=None):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            outbox.reconcile(conn, store, send_enabled, now or native._utc_now())

    def consented_day(self, start):
        with self._open_metrics(self.reference) as (conn, store):
            return outbox.consented_day(conn, store, start)

    def _prepare_export_package(self):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            outbox.create_pending(conn, store, native._utc_now())

    def _pending_exports(self):
        with self._open_metrics(self.reference) as (conn, store):
            return outbox.pending_exports(conn, store)

    def _mark_package_exported(self, package_id):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            records.change_package(conn, store, packages, package_id, {"exported_at": native._isoformat(native._utc_now())}, packages.c.exported_at.is_(None))

    def _expired_packages(self, cutoff):
        with self._open_metrics(self.reference) as (conn, store):
            return outbox.expired_packages(conn, store, cutoff)

    def _prune_packages(self, removed, cutoff):
        with self._open_metrics(self.reference, write=True) as (conn, store):
            outbox.prune(conn, store, removed, cutoff)
