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

@dataclass(frozen=True)
class TranscriptLimits:
    resume_limit: object
    export_limit: object
    resume_error: object
    export_error: object

@dataclass(frozen=True)
class HistoryOwnership:
    history_row: object
    owner_user: object
    same_owner: object
    owners_agree: object

@dataclass(frozen=True)
class SessionEffects:
    deleted: object
    purge_profile: object
    collect_media: object
    release_media: object

class SessionContext:
    def __init__(self, transactions, scope, *, own_profile, profile, transcript_limits, ownership, effects, is_context_summary, routes, media):
        scope.require_store_id()
        self.transactions = transactions
        self.scope = scope
        self.own_profile = own_profile
        self.profile = profile
        self.transcript_limits = transcript_limits
        self.ownership = ownership
        self.effects = effects
        self.is_context_summary = is_context_summary
        self.routes = routes
        self.media = media
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
