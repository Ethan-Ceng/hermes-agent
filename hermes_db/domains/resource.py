"""A caller-owned business domain view over a selected technical backend."""

from contextlib import contextmanager
from functools import wraps
import os

from hermes_db.errors import StorageClosedError


class DomainResource:
    def __init__(self, name, backend):
        self.name = name
        self._backend = backend
        self.settings, self.scope = backend.settings, backend.scope
        self.sqlite_path, self._transactions = backend.sqlite_path, backend.transactions
        self._pid = os.getpid()
        self._closed = False

    def _assert_open(self):
        if self._closed or self._pid != os.getpid():
            raise StorageClosedError("Domain resource is closed or belongs to another process; acquire it again")

    @contextmanager
    def read(self):
        self._assert_open()
        with self._backend.read() as conn:
            yield conn

    @contextmanager
    def write(self, *, lock_timeout=None):
        self._assert_open()
        with self._backend.write(lock_timeout=lock_timeout) as conn:
            yield conn

    def close(self):
        # Each acquisition closes its business view; the process owns the driver pool.
        self._closed = True

    def __enter__(self):
        self._assert_open()
        return self

    def __exit__(self, *_exc):
        self.close()


def _bound_method(activate, function, *bound):
    @wraps(function)
    def call(*args, **kwargs):
        with activate():
            return function(*bound, *args, **kwargs)
    return call
