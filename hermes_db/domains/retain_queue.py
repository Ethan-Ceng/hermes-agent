"""Queue identity pins Profile/database and remote destination, excluding API credentials."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class RetainQueueRef:
    profile_home: Path
    store_id: str
    target: str
    destination_id: str
    plugin_id: str = "retaindb"


def capture_queue(profile_home, destination_id):
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.move_values import resource_key
    with acquire_profile_domain("retain_queue", profile_home=profile_home) as resource:
        return RetainQueueRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions), destination_id)


@contextmanager
def open_queue(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.move_values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("retain_queue", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured RetainDB backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured RetainDB database target changed; reopen its owning provider")
        with (resource.write() if write else resource.read()) as conn:
            yield conn
