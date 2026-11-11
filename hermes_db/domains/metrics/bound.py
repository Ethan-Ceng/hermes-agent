"""Owner-only metric views over an existing receipt or authority transaction source."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BoundMetricsRef:
    scope: object
    source: object = field(repr=False, compare=False)

    @property
    def profile_home(self):
        return self.scope.profile_home




def bound_store(scope, source):
    from hermes_db.domains.metrics.postgres.store import PostgresMetricsStore
    from hermes_db.domains.metrics.api import open_metrics
    return PostgresMetricsStore(BoundMetricsRef(scope, source), open_metrics=open_metrics)
