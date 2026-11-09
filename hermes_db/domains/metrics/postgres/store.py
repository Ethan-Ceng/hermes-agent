"""Selected PG metrics store; native code supplies only pure contracts and formatting."""

import json
from datetime import timedelta
from pathlib import Path
from hermes_cli.observability import shared_metrics as native
from hermes_db.domains.metrics.api import capture_metrics, open_metrics
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.metrics.postgres import records, outbox
from hermes_db.tables.metrics import packages


class PostgresMetricsStore(native.SharedMetricsStore):
    backend = "postgresql"

    def __init__(self, database_path=None, outbox_directory=None, *, profile_home=None):
        self.reference = capture_metrics(profile_home)
        self.profile_home = self.reference.profile_home
        # The legacy SQLite path is never used to infer a Profile or opened in PG.
        self.database_path = None
        root = self.profile_home / "telemetry" / "shared_metrics"
        self.outbox_directory = Path(outbox_directory) if outbox_directory is not None else root / "postgresql" / "outbox"

    def _connection(self, **kwargs):
        raise StorageConfigurationError("PG metrics expose named operations, not a SQLite connection")

    def _write(self, **kwargs):
        raise StorageConfigurationError("PG metrics expose named operations, not a SQLite write transaction")

    def _record_once_per_interval(self, state_key, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        with open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now(), interval=True)

    def _record_once_ever(self, state_key, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        with open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now())

    def install_snapshot_due(self):
        with open_metrics(self.reference) as (conn, store):
            previous = self._parse_state_timestamp(records.get_state(conn, store, native._INSTALL_SNAPSHOT_STATE_KEY))
        now = native._utc_now()
        return previous is None or previous > now or now >= previous + timedelta(hours=24)

    def record_counter(self, metric_name, dimensions, resource, amount=1):
        self._validate_counter(metric_name, dimensions, resource)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1 or (amount != 1 and metric_name not in native.SUM_METRICS):
            raise ValueError(f"Unsupported amount for shared metric: {metric_name}")
        with open_metrics(self.reference, write=True) as (conn, store):
            records.record(conn, store, metric_name, dimensions, resource, native._utc_now(), amount)

    def record_counter_once_per_day(self, metric_name, dimensions, resource):
        self._validate_counter(metric_name, dimensions, resource)
        state_key = f"{native._DAILY_ONCE_STATE_PREFIX}{metric_name}:" + native._compact_json({key: value for key, value in dimensions.items() if key != "surface"})
        with open_metrics(self.reference, write=True) as (conn, store):
            return records.once(conn, store, state_key, metric_name, dimensions, resource, native._utc_now(), daily=True)

    def update_rollup_state(self, state_key, update):
        with open_metrics(self.reference, write=True) as (conn, store):
            records.rollup(conn, store, state_key, update)

    def _latched(self, prefix):
        with open_metrics(self.reference) as (conn, store):
            return records.latched(conn, store, prefix)

    def counter_snapshot(self):
        with open_metrics(self.reference) as (conn, store):
            return records.snapshot(conn, store)

    def drain_deferred(self, busy_timeout_ms=native._SCHEMA_BUSY_TIMEOUT_MS):
        # PG operations commit synchronously or raise; none are queued in memory.
        return None

    def create_and_export_package(self):
        with open_metrics(self.reference, write=True) as (conn, store):
            outbox.create_pending(conn, store, native._utc_now())
        return self._export_and_prune()

    def _create_pending_packages_if_due(self):
        with open_metrics(self.reference, write=True) as (conn, store):
            outbox.create_pending(conn, store, native._utc_now(), due=True)

    def _create_package(self):
        with open_metrics(self.reference, write=True) as (conn, store):
            return outbox.create_one(conn, store, native._utc_now())

    def _export_pending_packages(self):
        with open_metrics(self.reference) as (conn, store):
            rows = outbox.pending_exports(conn, store)
        exported = []
        if rows:
            native._ensure_private(self.outbox_directory, 0o700)
        for row in rows:
            path = self.outbox_directory / f"{row['package_id']}.json"
            native.atomic_json_write(path, json.loads(row["payload_json"]), indent=None, separators=(",", ":"), sort_keys=True, mode=0o600)
            with open_metrics(self.reference, write=True) as (conn, store):
                records.change_package(conn, store, packages, row["package_id"], {"exported_at": native._isoformat(native._utc_now())}, packages.c.exported_at.is_(None))
            exported.append(path)
        return exported

    def _prune_expired_history(self, *, now=None):
        cutoff = native._isoformat((now or native._utc_now()) - timedelta(days=native._LOCAL_HISTORY_RETENTION_DAYS))
        with open_metrics(self.reference) as (conn, store):
            ids = outbox.expired_packages(conn, store, cutoff)
        removed = []
        for package_id in ids:
            try:
                (self.outbox_directory / f"{package_id}.json").unlink(missing_ok=True)
                removed.append(package_id)
            except OSError:
                native.logger.warning("Unable to prune expired shared-metrics package %s", package_id, exc_info=True)
        with open_metrics(self.reference, write=True) as (conn, store):
            outbox.prune(conn, store, removed, cutoff)

    def reconcile_send_consent(self, send_enabled, *, now=None):
        with open_metrics(self.reference, write=True) as (conn, store):
            outbox.reconcile(conn, store, send_enabled, now or native._utc_now())

    def consented_day(self, start):
        with open_metrics(self.reference) as (conn, store):
            return outbox.consented_day(conn, store, start)
