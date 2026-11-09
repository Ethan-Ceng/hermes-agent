"""SDK-compatible shared ratchets; durable reads still validate the dataset generation."""

import asyncio
from contextlib import asynccontextmanager

from hermes_db.domains.plugin_storage.matrix.postgres import codec
from hermes_db.errors import StorageClosedError, StorageConflictError
from hermes_db.domains.plugin_storage.matrix.postgres.operations import sessions


class OlmSessions:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.owner = None
        self.values = {}
        self.failed = False
        self.writes = 0

    @asynccontextmanager
    async def guard(self):
        # Explicit SDK transactions take the async gate before the database root lock too.
        if self.store.runtime is not None:
            from hermes_db.errors import StorageError
            from hermes_db.domains.plugin_storage.matrix.postgres.failures import remember
            try:
                self.store.runtime._actor()
            except StorageError as error:
                remember(error)
                raise
        task = asyncio.current_task()
        if self.owner is task:
            yield
            return
        async with self.lock:
            self.owner = task
            try:
                yield
            finally:
                self.owner = None

    def require_usable(self):
        if self.failed:
            from hermes_db.domains.plugin_storage.matrix.postgres.failures import remember
            error = StorageClosedError("Olm persistence outcome is uncertain; recreate the Matrix crypto store before retrying")
            remember(error)
            raise error

    async def read(self, key, *, latest=False):
        async with self.guard():
            self.require_usable()
            rows = await self.store._call(sessions.get_sessions, sender_key=key, latest=latest)
            self.require_usable()
            result = []
            for row in rows:
                identity = (key, row["session_id"])
                if identity not in self.values:
                    self.values[identity] = codec.restore_session(row, self.store.pickle_key)
                result.append(self.values[identity])
            return result

    async def save(self, key, session, *, add=False):
        try:
            await self._save(key, session, add=add)
        except BaseException:
            # SDK mutation precedes this call, including the wait for the async gate.
            self.failed = True
            raise

    async def _save(self, key, session, *, add):
        async with self.guard():
            self.require_usable()
            identity = (key, session.id)
            old = self.values.get(identity)
            if old is not None and old is not session:
                from hermes_db.domains.plugin_storage.matrix.postgres.failures import remember
                error = StorageConflictError("A stale independent Olm session cannot replace the active ratchet")
                remember(error)
                raise error
            record = codec.session_record(key, session, self.store.pickle_key)
            await self.store._call(sessions.add_session if add else sessions.update_session, write=True, record=record)
            self.values[identity] = session
            self.writes += 1
