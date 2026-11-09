"""Owner-only metric views over an existing receipt or authority transaction source."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass(frozen=True)
class BoundMetricsRef:
    scope: object
    source: object = field(repr=False, compare=False)

    @property
    def profile_home(self):
        return self.scope.profile_home


@contextmanager
def open_bound(reference, *, write=False):
    from hermes_db.domains.metrics.postgres.records import lock_store
    resource = SimpleNamespace(scope=reference.scope)
    with (reference.source.write() if write else reference.source.read()) as conn:
        if write:
            lock_store(conn, resource)
        yield conn, resource


def bound_store(scope, source):
    from hermes_db.domains.metrics.postgres.store import PostgresMetricsStore
    return PostgresMetricsStore(BoundMetricsRef(scope, source))
