"""Use the existing router lifecycle with PG claim rows and captured ownership."""

import time
from hermes_db.domains.rooms.postgres.router_claims import claim_router_call, release_router_call
from tui_gateway.hosted_room_router_lifecycle import RouterCallLifecycle, CLAIM_TTL_SECONDS
from hermes_db.domains.rooms.api import RoomStoreRef, normalize_location
from gateway.hosted_room_storage import capture_room_store, open_room_store


class PostgresRouterCalls(RouterCallLifecycle):
    def __init__(self, db_path, *, clock=time.time):
        location = normalize_location(db_path)
        # Base lifecycle state does not contain a native SQL connection.
        self._db_path = location if isinstance(location, RoomStoreRef) else capture_room_store()
        self._clock = clock
        import threading
        import uuid
        self._owner = uuid.uuid4().hex
        self._lock, self._inflight = threading.Lock(), set()

    def _claim(self, key):
        now = self._clock()
        with open_room_store(self._db_path) as store, store.write() as conn:
            return claim_router_call(conn, store, key, self._owner, now, CLAIM_TTL_SECONDS)

    def _release(self, key):
        with open_room_store(self._db_path) as store, store.write() as conn:
            release_router_call(conn, store, key, self._owner)
