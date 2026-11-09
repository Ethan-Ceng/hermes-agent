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


def capture_metrics(profile_home=None):
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.integration.transfer.move_values import resource_key
    with acquire_profile_domain("metrics", profile_home=profile_home) as resource:
        return MetricsRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions))


@contextmanager
def open_metrics(reference, *, write=False):
    from hermes_db.domains.metrics_bound import BoundMetricsRef, open_bound
    if isinstance(reference, BoundMetricsRef):
        with open_bound(reference, write=write) as value:
            yield value
        return
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.integration.transfer.move_values import resource_key
    from hermes_db.repositories.metrics import lock_store
    with _owning_profile(reference.profile_home), acquire_profile_domain("metrics", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured metrics backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured metrics database target changed; reopen its owning runtime")
        with (resource.write() if write else resource.read()) as conn:
            if write:
                lock_store(conn, resource)
            yield conn, resource
