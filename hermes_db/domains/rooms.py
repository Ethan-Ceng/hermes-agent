"""Captured room ownership, never inferred from the legacy SQLite location argument."""

from dataclasses import dataclass
from functools import wraps
from importlib import import_module
from pathlib import Path
from contextlib import contextmanager

from hermes_db.core.resource import DomainResource
from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class RoomStoreRef:
    profile_home: Path
    store_id: str
    target: str


def normalize_location(location):
    if isinstance(location, DomainResource):
        return room_reference(location)
    return location if isinstance(location, RoomStoreRef) else Path(location)


def location_root(location):
    return location.profile_home if isinstance(location, RoomStoreRef) else Path(location).parent


def room_reference(store):
    from hermes_db.integration.transfer.move_values import resource_key
    return RoomStoreRef(store.scope.profile_home, store.scope.require_store_id(), resource_key(store._transactions))


def capture_room_store(profile_home=None):
    from hermes_db.factory import acquire_profile_domain
    with acquire_profile_domain("rooms", profile_home=profile_home) as store:
        if store.settings.backend != "postgresql":
            raise StorageConfigurationError("A PG room reference requires PostgreSQL storage")
        return room_reference(store)


def is_postgresql_location(location):
    from hermes_cli.db_setup import storage_backend
    return isinstance(location, (RoomStoreRef, DomainResource)) or storage_backend() == "postgresql"


def assert_sqlite_location(location):
    if is_postgresql_location(location):
        raise StorageConfigurationError("The selected PostgreSQL room store cannot open a private SQLite connection")


@contextmanager
def open_room_store(reference):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    with _owning_profile(reference.profile_home), acquire_profile_domain("rooms", profile_home=reference.profile_home) as store:
        if store.settings.backend != "postgresql" or store.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured room storage backend or store_id changed")
        if room_reference(store).target != reference.target:
            raise StorageConfigurationError("Captured room database target changed; reopen its owning runtime")
        yield store


def room_operation(topic):
    def decorate(sqlite_operation):
        @wraps(sqlite_operation)
        def operation(db_path, *args, **kwargs):
            from hermes_cli.db_setup import _owning_profile, storage_backend
            if isinstance(db_path, DomainResource):
                if db_path.name != "rooms" or db_path.settings.backend != "postgresql":
                    raise StorageConfigurationError("Room operations require their captured room resource")
                module = import_module(f"hermes_db.operations.{topic}")
                with _owning_profile(db_path.scope.profile_home):
                    return getattr(module, sqlite_operation.__name__)(db_path, *args, **kwargs)
            if not isinstance(db_path, RoomStoreRef) and storage_backend() == "sqlite":
                return sqlite_operation(db_path, *args, **kwargs)
            reference = db_path if isinstance(db_path, RoomStoreRef) else capture_room_store()
            with open_room_store(reference) as store:
                module = import_module(f"hermes_db.operations.{topic}")
                return getattr(module, sqlite_operation.__name__)(store, *args, **kwargs)
        return operation
    return decorate
