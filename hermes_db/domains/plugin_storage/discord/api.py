"""Captured Discord ledger ownership and bounded Core units of work."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class DiscordRef:
    profile_home: Path
    store_id: str
    target: str
    plugin_id: str = "discord"


def capture_discord(profile_home):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with acquire_profile_domain("discord_recovery", profile_home=profile_home) as resource:
        return DiscordRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions))


@contextmanager
def open_discord(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("discord_recovery", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured Discord backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured Discord database target changed; reopen its owning adapter")
        with (resource.write() if write else resource.read()) as conn:
            yield conn
