"""Plugin references pin Profile/database identity and namespace across thread hops."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class PluginRef:
    profile_home: Path
    store_id: str
    target: str
    plugin_id: str
    namespace: str


def capture_plugin(plugin_id, namespace, profile_home):
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with acquire_profile_domain("plugins", profile_home=profile_home) as resource:
        return PluginRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions), plugin_id, namespace)


@contextmanager
def open_plugin(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("plugins", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured plugin backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured plugin database target changed; reopen its owning runtime")
        with (resource.write() if write else resource.read()) as conn:
            yield conn
