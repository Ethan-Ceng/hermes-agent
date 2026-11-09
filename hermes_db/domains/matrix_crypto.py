"""Driver-independent Matrix identity plus captured shared-PG target and namespace generation."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class MatrixRef:
    profile_home: Path
    store_id: str
    target: str
    account_key: str
    owner_device: str
    generation: str | None = None


def capture_matrix(profile_home, homeserver, account_id, device_id):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.access import _owner_only
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.integration.transfer.move_values import resource_key
    from hermes_db.backends.postgresql.transactions import Transactions
    _owner_only()
    if not homeserver or not account_id or not device_id:
        raise StorageConfigurationError("PG Matrix encryption requires authenticated homeserver, user and device identities")
    settings, scope = resolve_db_configuration(profile_home)
    if settings.backend != "postgresql":
        raise StorageConfigurationError("The selected Matrix CryptoStore requires PostgreSQL storage")
    pg = settings.postgresql
    target = resource_key(Transactions(get_engine(pg), pg.schema))
    return MatrixRef(scope.profile_home, scope.require_store_id(), target,
        hashlib.sha256(json.dumps([homeserver.rstrip("/"), account_id], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest(), device_id)


@contextmanager
def resource_for(reference):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.integration.transfer.move_values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("matrix_crypto", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured Matrix backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured Matrix database target changed; reopen its owning adapter")
        yield resource


@contextmanager
def unit_of_work(reference, *, write=False):
    from hermes_db.repositories.matrix_crypto import check_generation
    with resource_for(reference) as resource, (resource.write() if write else resource.read()) as conn:
        check_generation(conn, reference, lock=write)
        yield conn
