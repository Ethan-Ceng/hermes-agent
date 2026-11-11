"""Core claims with the unchanged sender transport, response and backoff contract."""

import logging
logger = logging.getLogger("hermes_cli.observability.shared_metrics_sender")
from hermes_db.domains.metrics.postgres import outbox as metric_sender
from hermes_db.errors import StorageConfigurationError, StorageError


class PostgresMetricsSender:
    def _write(self):
        raise StorageConfigurationError("PG sender exposes named claim operations, not SQLite transactions")

    def _claim_next(self, now, seen):
        with self._store._open_metrics(self._store.reference, write=True) as (conn, store):
            return metric_sender.claim(conn, store, now, seen)

    def _mark(self, package_id, *, token=None, **columns):
        with self._store._open_metrics(self._store.reference, write=True) as (conn, store):
            metric_sender.mark(conn, store, package_id, token, columns)

    def _renew_claim(self, package_id, token):
        try:
            with self._store._open_metrics(self._store.reference, write=True) as (conn, store):
                return metric_sender.renew(conn, store, package_id, token, self._now())
        except StorageError:
            logger.warning("Unable to renew shared-metrics claim", exc_info=True)
            return False

    def _reconcile(self, *, send_enabled):
        try:
            self._store.reconcile_send_consent(send_enabled, now=self._now())
        except StorageError:
            logger.warning("Unable to reconcile shared-metrics consent", exc_info=True)
