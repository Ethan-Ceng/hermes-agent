"""Remember PG failures even when an SDK handler catches them internally."""

from contextlib import contextmanager
from contextvars import ContextVar

_active = ContextVar("matrix_storage_failures", default=None)


def remember(error):
    failures = _active.get()
    if failures is not None:
        failures.append(error)


@contextmanager
def checkpoint():
    failures = []
    token = _active.set(failures)
    try:
        yield
        if failures:
            raise failures[0]
    finally:
        _active.reset(token)
