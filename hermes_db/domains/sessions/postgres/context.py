"""One captured session resource; component reads share its pin and close state."""
from contextlib import contextmanager
from dataclasses import dataclass
import threading
from hermes_db.errors import StorageClosedError

_snapshots = threading.local()

def _pins():
    if not hasattr(_snapshots, "connections"):
        _snapshots.connections = {}
    return _snapshots.connections

@dataclass(frozen=True)
class ReadSnapshot:
    connection: object
    pinned: bool = True

    def __call__(self):
        return not self.connection.closed and self.connection.in_transaction()

class SessionContext:
    def __init__(self, transactions, scope, *, own_profile, profile):
        scope.require_store_id()
        self.transactions = transactions
        self.scope = scope
        self.own_profile = own_profile
        self.profile = profile
        self.closed = False

    def assert_open(self):
        if self.closed:
            raise StorageClosedError("Session store is closed")

    @contextmanager
    def read(self):
        self.assert_open()
        pinned = _pins().get(id(self))
        if pinned is not None:
            yield pinned
            return
        with self.transactions.read() as conn:
            yield conn

    @contextmanager
    def write(self):
        self.assert_open()
        with self.transactions.write() as conn:
            yield conn

    @contextmanager
    def transcript_read_snapshot(self):
        self.assert_open()
        existing = _pins().get(id(self))
        if existing is not None:
            yield ReadSnapshot(existing)
            return
        with self.transactions.read() as conn:
            _pins()[id(self)] = conn
            try:
                yield ReadSnapshot(conn)
            finally:
                _pins().pop(id(self))

    def close(self):
        if self.closed:
            return
        try:
            self.usage_writer.close()
        finally:
            self.closed = True
