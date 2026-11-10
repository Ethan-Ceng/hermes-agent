"""A resolved data-source selection with short technical units of work."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path

from hermes_db.errors import StorageClosedError, StorageNotReadyError
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


@dataclass(frozen=True)
class BackendResource:
    settings: DatabaseSettings
    scope: DatabaseScope
    sqlite_path: Path | None = None
    transactions: object = field(default=None, repr=False)
    _pid: int = field(default_factory=os.getpid, init=False, repr=False)

    def _unit_of_work(self):
        if self._pid != os.getpid():
            raise StorageClosedError("Backend resource belongs to another process; acquire it again")
        if self.transactions is None:
            raise StorageNotReadyError("SQLite resources use their native implementation, not PG units of work")
        return self.transactions

    @contextmanager
    def read(self):
        with self._unit_of_work().read() as conn:
            yield conn

    @contextmanager
    def write(self, *, lock_timeout=None):
        with self._unit_of_work().write(lock_timeout=lock_timeout) as conn:
            yield conn
