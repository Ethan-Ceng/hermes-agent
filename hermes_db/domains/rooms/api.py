"""Captured room ownership, never inferred from the legacy SQLite location argument."""

from dataclasses import dataclass
from pathlib import Path

from hermes_db.domains.resource import DomainResource




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
    from hermes_db.core.values import resource_key
    return RoomStoreRef(store.scope.profile_home, store.scope.require_store_id(), resource_key(store._transactions))












class RoomResource(DomainResource):
    def __init__(self, backend, *, local_authority_gateway_id):
        super().__init__("rooms", backend)
        self.local_authority_gateway_id = local_authority_gateway_id
