"""Immutable ownership and bounded units of work, without a SQLite SQL facade."""

from contextlib import contextmanager
import os
from pathlib import Path

from hermes_db.errors import StorageClosedError, StorageNotReadyError


class DomainResource:
    def __init__(self, name, settings, scope, *, sqlite_path=None, transactions=None):
        self.name = name
        self.settings = settings
        self.scope = scope
        self.sqlite_path = Path(sqlite_path) if sqlite_path is not None and settings.backend == "sqlite" else None
        self._transactions = transactions
        self._pid = os.getpid()
        self._closed = False

    def _assert_open(self):
        if self._closed or self._pid != os.getpid():
            raise StorageClosedError("Domain resource is closed or belongs to another process; acquire it again")

    def _unit_of_work(self):
        self._assert_open()
        if self._transactions is None:
            raise StorageNotReadyError("SQLite domains use their native implementation, not PG units of work")
        return self._transactions

    @contextmanager
    def read(self):
        with self._unit_of_work().read() as conn:
            yield conn

    @contextmanager
    def write(self, *, lock_timeout=None):
        with self._unit_of_work().write(lock_timeout=lock_timeout) as conn:
            yield conn

    def close(self):
        # Connections belong to short operations; the process owns the shared pool.
        self._closed = True

    def __enter__(self):
        self._assert_open()
        return self

    def __exit__(self, *_exc):
        self.close()
