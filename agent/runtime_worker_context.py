"""A reserved in-process child uses its own authenticated claim on owner RPC."""

from contextlib import contextmanager
from contextvars import ContextVar

_store = ContextVar("runtime_worker_store", default=None)


def scoped_worker_store():
    return _store.get()


@contextmanager
def worker_store_context(store):
    from agent.runtime_session_store import RuntimeSessionStore
    token = _store.set(store if isinstance(store, RuntimeSessionStore) else None)
    try:
        yield
    finally:
        _store.reset(token)
