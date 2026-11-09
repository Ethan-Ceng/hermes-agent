"""Profile-owned Responses persistence; failures never fall back to memory."""

import asyncio
from contextlib import contextmanager
import json
import threading
import time

from sqlalchemy import func, select

from hermes_db.errors import StorageClosedError
from hermes_db.operations import api as operations
from hermes_db.repositories import api as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.api import conversations, responses, response_keys, response_admissions


class PostgresResponseStore:
    @property
    def database_identity(self):
        from hermes_db.health import storage_identity
        return storage_identity(self._store)

    def __init__(self, session_store, *, api_scope="", max_size=100, max_identities=None, initialize=True):
        self._store, self.scope, self.api_scope = session_store, session_store.scope, api_scope
        self._max_size, self._max_identities = max_size, max_identities or 10 * max_size
        self._closed, self._local = False, threading.local()
        self._needs_maintenance = True
        if initialize:
            with self._transaction():
                pass

    @contextmanager
    def _transaction(self):
        if self._closed:
            raise StorageClosedError("Response store is closed")
        current = getattr(self._local, "connection", None)
        if current is not None:
            yield current
            return
        with self._store._profile.activate(), self._store._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            if self._needs_maintenance:
                operations.settle_keys(conn, self.scope, self.api_scope)
                operations.evict(conn, self.scope, self.api_scope, self._max_size, self._max_identities, time.time())
            self._local.connection = conn
            try:
                yield conn
            finally:
                self._local.connection = None
        self._needs_maintenance = False

    def atomically(self, fn, /, *args, **kwargs):
        with self._transaction():
            return fn(*args, **kwargs)

    async def off_loop(self, fn, /, *args, **kwargs):
        return await asyncio.to_thread(self.atomically, fn, *args, **kwargs)

    def get(self, response_id):
        with self._transaction() as conn:
            raw = repo.body(conn, self.scope, self.api_scope, response_id)
            if raw is None:
                return None
            conn.execute(responses.update().where(repo.where(self.scope, self.api_scope, responses), responses.c.response_id == response_id)
                .values(accessed_at=time.time()))
            try:
                return json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                conn.execute(responses.delete().where(repo.where(self.scope, self.api_scope, responses), responses.c.response_id == response_id))
                return None

    def put(self, response_id, data):
        encoded = json.dumps(data, default=str)
        with self._transaction() as conn:
            repo.put(conn, self.scope, self.api_scope, response_id, encoded, time.time())
            operations.evict(conn, self.scope, self.api_scope, self._max_size, self._max_identities, time.time())

    def bind_request_key(self, key, fingerprint, *, model=None):
        with self._transaction() as conn:
            return repo.bind_key(conn, self.scope, self.api_scope, key, fingerprint, model, time.time())

    def request_model(self, key, fallback):
        with self._transaction() as conn:
            row = repo.key(conn, self.scope, self.api_scope, key)
            if row is None:
                return fallback
            return json.loads(row["model_json"])

    def output_index(self, key, item_id):
        with self._transaction() as conn:
            return repo.output_index(conn, self.scope, self.api_scope, key, item_id)

    def order_output(self, key, items):
        return self.atomically(lambda: sorted(items, key=lambda item: self.output_index(key, item["id"])))

    def request_created_at(self, key):
        with self._transaction() as conn:
            row = repo.key(conn, self.scope, self.api_scope, key)
            return row["created_at"] if row else None

    def request_key_matches(self, key, fingerprint):
        with self._transaction() as conn:
            row = repo.key(conn, self.scope, self.api_scope, key)
            return row is None or row["fingerprint"] == fingerprint

    def request_admission(self, key):
        with self._transaction() as conn:
            return repo.admission(conn, self.scope, self.api_scope, key)

    def bind_request_admission(self, key, admission_id):
        with self._transaction() as conn:
            repo.bind_admission(conn, self.scope, self.api_scope, key, admission_id)

    def resolve_request_admission(self, key, request_id):
        """Authenticated edge lookup/repair on this Responses transaction's connection."""
        with self._transaction() as conn:
            return operations.resolve_admission(conn, self.scope, self.api_scope, key, request_id)

    def forget_unadmitted_request(self, key):
        with self._transaction() as conn:
            bound = select(response_admissions.c.request_key).where(repo.where(self.scope, self.api_scope, response_admissions),
                response_admissions.c.request_key == key).exists()
            conn.execute(response_keys.delete().where(repo.where(self.scope, self.api_scope, response_keys), response_keys.c.request_key == key, ~bound))

    def delete(self, response_id):
        with self._transaction() as conn:
            return operations.delete(conn, self.scope, self.api_scope, response_id, time.time())

    def get_conversation(self, name):
        with self._transaction() as conn:
            return conn.scalar(select(conversations.c.response_id).where(repo.where(self.scope, self.api_scope, conversations), conversations.c.name == name))

    def set_conversation(self, name, response_id):
        with self._transaction() as conn:
            repo.set_conversation(conn, self.scope, self.api_scope, name, response_id)

    def close(self):
        self._closed = True

    def __len__(self):
        with self._transaction() as conn:
            return conn.scalar(select(func.count()).select_from(responses).where(repo.where(self.scope, self.api_scope, responses)))
