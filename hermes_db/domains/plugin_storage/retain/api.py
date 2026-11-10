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


class WorkerRetainQueueRef(RetainQueueRef):
    __slots__ = ('_resource',)

    def __init__(self, resource, destination_id):
        super().__init__(resource.scope.profile_home, resource.scope.require_store_id(), resource.target, destination_id)
        object.__setattr__(self, '_resource', resource)

    def _result(self, result):
        if isinstance(result, dict) and isinstance(result.get('fingerprint'), str):
            return dict(result, fingerprint=bytes.fromhex(result['fingerprint']))
        return result

    def command(self, name, **values):
        return self._result(self._resource.command('retain_queue.' + name, dict(destination_id=self.destination_id, **values)))

    def query(self, name, **values):
        return self._result(self._resource.query('retain_queue.' + name, dict(destination_id=self.destination_id, **values)))


def capture_queue(profile_home, destination_id):
    from agent.runtime_domain_store import worker_resource
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    worker = worker_resource('retain_queue', profile_home=profile_home)
    if worker is not None:
        return WorkerRetainQueueRef(worker, destination_id)
    with acquire_profile_domain("retain_queue", profile_home=profile_home) as resource:
        return RetainQueueRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions), destination_id)


@contextmanager
def open_queue(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("retain_queue", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured RetainDB backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured RetainDB database target changed; reopen its owning provider")
        with (resource.write() if write else resource.read()) as conn:
            yield conn
