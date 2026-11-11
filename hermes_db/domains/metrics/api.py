"""Captured metrics ownership survives thread hops without borrowing the launch profile."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class MetricsRef:
    profile_home: Path
    store_id: str
    target: str





@contextmanager
def open_metrics(reference, *, write=False):
    from types import SimpleNamespace
    from hermes_db.domains.metrics.postgres.records import lock_store
    resource = SimpleNamespace(scope=reference.scope)
    with (reference.source.write() if write else reference.source.read()) as conn:
        if write:
            lock_store(conn, resource)
        yield conn, resource
