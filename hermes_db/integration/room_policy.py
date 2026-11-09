"""PG policy composition; each operation borrows only a bounded connection."""
from hermes_db.domains.rooms import rules as _storage_shared_1

from collections.abc import Mapping
from hermes_db.domains.rooms import rules as hosted_rooms
from hermes_db.domains.rooms.postgres.lifecycle import read_events
from hermes_db.domains.rooms import rules as native
from hermes_db.domains.rooms.api import RoomStoreRef, capture_room_store, normalize_location, open_room_store
from hermes_db.domains.rooms.postgres import policy as operations, policy as reads


class PostgresRoomPolicy:
    def __init__(self, db_path, *, max_active_events=native.MAX_ACTIVE_POLICY_EVENTS):
        if isinstance(max_active_events, bool) or not isinstance(max_active_events, int) or max_active_events < 1:
            raise ValueError("max_active_events must be a positive integer")
        location = normalize_location(db_path)
        self.db_path = location if isinstance(location, RoomStoreRef) else capture_room_store()
        capacity = min(2**63 - 2, max(_storage_shared_1.MAX_ACTIVE_POLICY_EVENTS, max_active_events))
        with open_room_store(self.db_path) as store:
            self.max_active_events = operations.initialize(store, capacity)
        self.max_transcript_policy_events = min(2**63 - 2, _storage_shared_1.MAX_THREAD_TRANSCRIPT_EVENTS * (
            self.max_active_events + _storage_shared_1.MAX_ACTIVE_RETRY_RECEIPTS + 2))

    def sync(self, *, room_id, latest_seq):
        with open_room_store(self.db_path) as store:
            cursor = operations.ensure_cursor(store, room_id)
        while cursor < latest_seq:
            with open_room_store(self.db_path) as store:
                page = read_events(store, room_id=room_id, since_seq=cursor, limit=hosted_rooms.MAX_LOG_LIMIT)
            rows = [event for event in page.get("events", []) if isinstance(event, Mapping)]
            next_cursor = int(page.get("cursor") or cursor)
            if not rows or next_cursor <= cursor:
                raise RuntimeError("hosted room policy cursor did not advance")
            with open_room_store(self.db_path) as store:
                cursor = operations.apply_page(store, room_id, cursor, rows, next_cursor)
        return cursor

    def snapshot(self, *, room_id, latest_seq):
        self.sync(room_id=room_id, latest_seq=latest_seq)
        with open_room_store(self.db_path) as store:
            return operations.snapshot(store, room_id, max_active=self.max_active_events, max_transcript=self.max_transcript_policy_events)

    def publication_exists(self, **params):
        with open_room_store(self.db_path) as store:
            return reads.publication_exists(store, **params)

    def events_for_task(self, **params):
        with open_room_store(self.db_path) as store:
            return reads.events_for_task(store, max_active=self.max_active_events, max_transcript=self.max_transcript_policy_events, **params)

    def compact_completed(self, *, room_id):
        with open_room_store(self.db_path) as store:
            return operations.compact_completed(store, room_id)
