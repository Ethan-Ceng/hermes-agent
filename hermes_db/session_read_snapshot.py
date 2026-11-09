"""Pin one repeatable-read connection for a bounded transcript request."""
from contextlib import contextmanager
from dataclasses import dataclass
import threading

_snapshots = threading.local()


def _pins():
    if not hasattr(_snapshots, "connections"):
        _snapshots.connections = {}
    return _snapshots.connections


def pinned_connection(store):
    return _pins().get(id(store))


@dataclass(frozen=True)
class ReadSnapshot:
    connection: object
    pinned: bool = True

    def __call__(self):
        return not self.connection.closed and self.connection.in_transaction()


class SessionReadSnapshots:
    @contextmanager
    def transcript_read_snapshot(self):
        self._assert_open()
        existing = pinned_connection(self)
        if existing is not None:
            yield ReadSnapshot(existing)
            return
        with self._transactions.read() as conn:
            _pins()[id(self)] = conn
            try:
                yield ReadSnapshot(conn)
            finally:
                _pins().pop(id(self))
