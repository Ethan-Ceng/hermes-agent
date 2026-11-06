"""A scope-bound ownership token, never a long-running connection."""

from collections.abc import Callable
from threading import Lock

from hermes_db.contracts import SessionStore
from hermes_db.errors import StorageClosedError
from hermes_db.scope import DatabaseScope


class DatabaseHandle:
    def __init__(self, scope: DatabaseScope, sessions: SessionStore, runtime, release: Callable[[], None]):
        self._scope = scope
        self._sessions = sessions
        self._runtime = runtime
        self._release = release
        self._closed = False
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

    def _check_open(self):
        if self._closed:
            raise StorageClosedError("Database handle is closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._release()

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, *exc):
        self.close()
