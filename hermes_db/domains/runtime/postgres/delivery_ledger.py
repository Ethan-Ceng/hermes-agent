"""Instance-fenced PostgreSQL gateway delivery ledger, with opaque attempt proofs."""

from contextlib import contextmanager
import time
import uuid

from hermes_db.domains.runtime.postgres.operations import deliveries
from hermes_db.domains.runtime.postgres.queries import deliveries as repo


class PostgresDeliveryLedger:
    def __init__(self, session_store, *, instance_id=None, lease_ttl_seconds=300):
        self._store, self.scope = session_store, session_store.scope
        self.instance_id = instance_id or uuid.uuid4().hex
        self.lease_ttl_seconds = max(0.1, float(lease_ttl_seconds))
        self._store._assert_open()

    @contextmanager
    def _write(self):
        with self._store._profile.activate(), self._store._write() as conn:
            yield conn

    def record_obligation(self, **kwargs):
        with self._write() as conn:
            return deliveries.record(conn, self.scope, self.instance_id, self.lease_ttl_seconds, **kwargs)

    def record_crash_left_reply(self, **kwargs):
        with self._write() as conn:
            return deliveries.record_crash_left(conn, self.scope, **kwargs)

    def get_obligation(self, oid):
        with self._store._read() as conn:
            return repo.row(conn, self.scope, oid)

    def _mark(self, proof, state, error=""):
        with self._write() as conn:
            return deliveries.mark(conn, self.scope, self.instance_id, proof, state, self.lease_ttl_seconds, error)

    def mark_attempting(self, proof):
        return self._mark(proof, "attempting")

    def mark_delivered(self, proof):
        return self._mark(proof, "delivered")

    def mark_failed(self, proof, error=""):
        return self._mark(proof, "failed", error)

    def release_runtime_claim(self, proof, error=""):
        with self._write() as conn:
            return deliveries.release(conn, self.scope, self.instance_id, proof, error)

    def sweep_recoverable(self, now=None, *, deliverable_platforms=None, deliverable_targets=None):
        with self._write() as conn:
            return deliveries.sweep(conn, self.scope, self.instance_id, self.lease_ttl_seconds, time.time() if now is None else now,
                deliverable_platforms=deliverable_platforms, deliverable_targets=deliverable_targets)

    def sweep_failed_for_runtime(self, platform, now=None, *, profile=None):
        with self._write() as conn:
            return deliveries.sweep(conn, self.scope, self.instance_id, self.lease_ttl_seconds, time.time() if now is None else now,
                platform=platform, profile=profile)

    def pending_retries(self, now=None):
        with self._store._read() as conn:
            return deliveries.pending(conn, self.scope, self.instance_id, time.time() if now is None else now)
