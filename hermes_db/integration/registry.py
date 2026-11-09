"""Refcounted native stores per process/config/scope; never shared Connections."""

import atexit
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Event, RLock

from hermes_db.handle import DatabaseHandle


@dataclass(frozen=True)
class _Key:
    pid: int
    settings: object = field(repr=False)
    scope: object


@dataclass
class _Entry:
    ready: Event = field(default_factory=Event)
    store: object = None
    runtime: object = None
    refs: int = 0
    closing: bool = False


_lock = RLock()
_entries = {}


def _construct_store(settings, scope):
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.backends.postgresql.transactions import Transactions
    from hermes_db.schema import check_schema
    from hermes_db.integration.session_composition import create_session_store
    check_schema(settings)
    transactions = Transactions(get_engine(settings), settings.schema, lock_timeout=settings.write_lock_timeout_seconds,
        statement_timeout=settings.statement_timeout_seconds)
    return create_session_store(transactions, scope)


def _handle(key, entry):
    return DatabaseHandle(key.scope, entry.store, entry.runtime, lambda: _release(key, entry),
        valid=lambda: not entry.closing)


def _build(key, entry):
    from hermes_db.integration.runtime_composition import create_runtime_store
    try:
        store = _construct_store(key.settings, key.scope)
        try:
            runtime = create_runtime_store(store)
        except BaseException:
            store.close()
            raise
    except BaseException:
        with _lock:
            _entries.pop(key, None)
            entry.ready.set()
        raise
    with _lock:
        entry.store, entry.runtime, entry.refs = store, runtime, 1
        entry.ready.set()
        return _handle(key, entry)


def acquire(settings, scope):
    scope.require_store_id()
    key = _Key(os.getpid(), settings, scope)
    while True:
        with _lock:
            entry = _entries.get(key)
            if entry is None:
                entry = _entries[key] = _Entry()
                build = True
            elif entry.store is not None and not entry.closing:
                entry.refs += 1
                return _handle(key, entry)
            else:
                build = False
        if build:
            return _build(key, entry)
        # Construction and final usage flush happen outside the global lock.
        entry.ready.wait()


def _finish_close(key, entry):
    try:
        entry.store.close()
    finally:
        with _lock:
            if _entries.get(key) is entry:
                del _entries[key]
            entry.ready.set()


def _release(key, entry):
    with _lock:
        if _entries.get(key) is not entry or entry.closing or os.getpid() != key.pid:
            return
        entry.refs -= 1
        if entry.refs:
            return
        entry.closing = True
        entry.ready.clear()
    _finish_close(key, entry)


def close_all(directory=None):
    """Owner shutdown/unserve calls this after quiescing the affected consumers."""
    base = Path(directory).resolve() if directory is not None else None
    with _lock:
        selected = [(key, entry) for key, entry in _entries.items() if key.pid == os.getpid()
            and (base is None or key.scope.profile_home.is_relative_to(base))]
    count = 0
    for key, entry in selected:
        entry.ready.wait()
        with _lock:
            if _entries.get(key) is not entry:
                continue
            if entry.closing:
                close = False
            else:
                entry.closing = True
                entry.ready.clear()
                close = True
        if close:
            _finish_close(key, entry)
            count += 1
        else:
            entry.ready.wait()
    return count


atexit.register(close_all)
