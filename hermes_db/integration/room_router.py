"""Use the existing router lifecycle with PG claim rows and captured ownership."""

import time
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from tui_gateway.hosted_room_router_call import RouterCalls, CLAIM_TTL_SECONDS
from hermes_db.domains.rooms.api import RoomStoreRef, capture_room_store, normalize_location, open_room_store
from hermes_db.domains.rooms.postgres import repository as repo
from hermes_db.tables.room_policy import router_claims


class PostgresRouterCalls(RouterCalls):
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
            fields = repo.values(router_claims, dict(room_id=key[0], discussion_event_id=key[1], owner=self._owner, expires_at=now + CLAIM_TTL_SECONDS))
            statement = insert(router_claims).values(store_id=store.scope.require_store_id(), **fields)
            owner = conn.scalar(statement.on_conflict_do_update(index_elements=list(router_claims.primary_key.columns),
                set_=dict(owner=statement.excluded.owner, expires_at=statement.excluded.expires_at),
                where=router_claims.c.expires_at <= now).returning(router_claims.c.owner))
            return owner == self._owner

    def _release(self, key):
        with open_room_store(self._db_path) as store, store.write() as conn:
            conn.execute(delete(router_claims).where(repo.key(router_claims, store, dict(room_id=key[0], discussion_event_id=key[1], owner=self._owner))))
