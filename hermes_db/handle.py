"""A scope-bound ownership token, never a long-running connection."""

from collections.abc import Callable
import os
from threading import Lock

from hermes_db.contracts import SessionStore
from hermes_db.errors import StorageClosedError
from hermes_db.scope import DatabaseScope


class DatabaseHandle:
    def __init__(self, scope: DatabaseScope, sessions: SessionStore, runtime, release: Callable[[], None], *, valid=None):
        self._scope = scope
        self._sessions = sessions
        self._runtime = runtime
        self._release = release
        self._valid = valid
        self._closed = False
        self._pid = os.getpid()
        self._lock = Lock()

    @property
    def scope(self) -> DatabaseScope:
        return self._scope

    @property
    def sessions(self) -> SessionStore:
        self._check_open()
        return self._sessions

    @property
    def runtime(self):
        self._check_open()
        return self._runtime

    @property
    def is_open(self):
        return not self._closed and self._pid == os.getpid() and (self._valid is None or self._valid())

    def _check_open(self):
        if not self.is_open:
            raise StorageClosedError("Database handle is closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._pid == os.getpid():
            self._release()

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *exc):
        self.close()
