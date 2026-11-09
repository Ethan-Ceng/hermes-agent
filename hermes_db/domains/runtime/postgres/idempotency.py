"""Durable Run reservations; process-local memory is never a fallback."""

from contextlib import contextmanager
import hmac
import time
import uuid

from sqlalchemy import select

from hermes_db.errors import StorageClosedError
from hermes_db.domains.runtime.postgres.queries import api_runs as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.api import run_idempotency as table
from gateway.platforms.api_server_run_idempotency import _encode_status


class PostgresRunIdempotencyStore:
    RETENTION_SECONDS = 86400
    ACKNOWLEDGED_RETENTION_SECONDS = 86400

    def __init__(self, session_store):
        self._store, self.scope, self._closed = session_store, session_store.scope, False
        session_store._assert_open()

    @property
    def durable(self):
        return True

    @contextmanager
    def _transaction(self):
        if self._closed:
            raise StorageClosedError("Run idempotency store is closed")
        with self._store._profile.activate(), self._store._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            yield conn

    def _prune(self, conn, api_scope, now):
        repo.prune(conn, self.scope, api_scope, now, self.RETENTION_SECONDS, self.ACKNOWLEDGED_RETENTION_SECONDS)

    def reserve(self, scope, key, fingerprint, run_id, status, *, owner_pid=0, owner_started=0, retention_until=0):
        now, retention = time.time(), max(0.0, float(retention_until or 0))
        with self._transaction() as conn:
            self._prune(conn, scope, now)
            row = repo.find(conn, self.scope, scope, key)
            if row is not None:
                if retention:
                    repo.extend(conn, self.scope, scope, retention, table.c.idempotency_key == key, table.c.fingerprint == fingerprint)
                return ("reused" if hmac.compare_digest(row["fingerprint"], fingerprint) else "conflict"), repo.record(row)
            repo.insert(conn, self.scope, scope, key, fingerprint, run_id, status, owner_pid, owner_started, retention, now)
            return "created", repo.record(repo.find(conn, self.scope, scope, key))

    def lookup(self, scope, key, fingerprint, *, retention_until=0):
        now, retention = time.time(), max(0.0, float(retention_until or 0))
        with self._transaction() as conn:
            if retention:
                repo.extend(conn, self.scope, scope, retention, table.c.idempotency_key == key, table.c.fingerprint == fingerprint)
            self._prune(conn, scope, now)
            row = repo.find(conn, self.scope, scope, key)
            return ("missing", None) if row is None else (
                "reused" if hmac.compare_digest(row["fingerprint"], fingerprint) else "conflict", repo.record(row))

    def status_for_run(self, scope, run_id, *, retention_until=0):
        retention = max(0.0, float(retention_until or 0))
        with self._transaction() as conn:
            if retention:
                repo.extend(conn, self.scope, scope, retention, table.c.run_id == run_id)
            row = conn.execute(select(table).where(repo.where(self.scope, scope), table.c.run_id == run_id)).mappings().one_or_none()
            return {key: value for key, value in repo.record(row).items() if key != "run_id"} if row else None

    def find_or_close(self, scope, key):
        from gateway.hosted_room_peer import MAX_STATUS_GRANT_TTL_SECONDS
        from gateway.platforms.api_server_run_idempotency import _CLOSED_FINGERPRINT
        now = time.time()
        retention = now + MAX_STATUS_GRANT_TTL_SECONDS
        with self._transaction() as conn:
            self._prune(conn, scope, now)
            row = repo.find(conn, self.scope, scope, key)
            if row is None:
                repo.insert(conn, self.scope, scope, key, _CLOSED_FINGERPRINT, 'closed_' + uuid.uuid4().hex,
                            {'status': 'cancelled'}, 0, 0, retention, now)
            elif row['fingerprint'] == _CLOSED_FINGERPRINT:
                repo.extend(conn, self.scope, scope, retention, table.c.idempotency_key == key,
                            table.c.fingerprint == _CLOSED_FINGERPRINT)
            if row is None or row['fingerprint'] == _CLOSED_FINGERPRINT:
                return 'closed', None
            return 'found', repo.record(row)

    def extend_retention(self, scope, run_id, until):
        checked = max(0.0, float(until or 0))
        if not checked:
            return False
        with self._transaction() as conn:
            exists = conn.scalar(select(table.c.run_id).where(repo.where(self.scope, scope), table.c.run_id == run_id))
            repo.extend(conn, self.scope, scope, checked, table.c.run_id == run_id)
            return exists is not None

    def owns_run(self, scope, run_id):
        with self._transaction() as conn:
            return conn.scalar(select(table.c.run_id).where(repo.where(self.scope, scope), table.c.run_id == run_id)) is not None

    def update_status(self, run_id, status, *, scope):
        with self._transaction() as conn:
            conn.execute(table.update().where(repo.where(self.scope, scope), table.c.run_id == run_id)
                .values(status_json=_encode_status(status), updated_at=time.time()))

    def forget(self, scope, key):
        with self._transaction() as conn:
            conn.execute(table.delete().where(repo.where(self.scope, scope), table.c.idempotency_key == key))

    def close(self):
        self._closed = True
