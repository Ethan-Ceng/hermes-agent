"""PG sync waits for SDK handlers and propagates durable-storage failures to its checkpoint."""

import asyncio
from contextvars import ContextVar
import inspect

from mautrix.client import Client
from hermes_cli.db_setup import _owning_profile
from hermes_db.errors import StorageError


class PostgresMatrixClient(Client):
    def __init__(self, *args, profile_home, **kwargs):
        super().__init__(*args, **kwargs)
        self._profile_home = profile_home
        self._sync_tasks = ContextVar("matrix_sync_tasks", default=None)

    async def _catch_errors(self, handler, data):
        from hermes_db.domains.plugin_storage.matrix.postgres.failures import checkpoint
        with _owning_profile(self._profile_home), checkpoint():
            try:
                await handler(data)
            except StorageError:
                raise
            except Exception:
                self.log.exception("Failed to run Matrix handler")

    def dispatch_manual_event(self, event_type, data, include_global_handlers=False, force_synchronous=False, source=None):
        tasks = super().dispatch_manual_event(event_type, data, include_global_handlers=include_global_handlers,
            force_synchronous=True, source=source)
        batch = self._sync_tasks.get()
        if batch is not None:
            batch.extend(tasks)
        return tasks

    async def dispatch_sync_batch(self, data):
        # The SDK dispatches decrypted to-device descendants without awaiting their tasks.
        batch, results = [], []
        token = self._sync_tasks.set(batch)
        try:
            try:
                initial = self.handle_sync(data)
                if inspect.isawaitable(initial):
                    initial = await initial
                batch.extend(task for task in (initial or []) if task not in batch)
            except Exception as error:  # health: allow BLE001 -- drain SDK descendant tasks before returning the parser failure to the sync boundary
                results.append(error)
            index = 0
            while index < len(batch):
                pending = batch[index:]
                index = len(batch)
                results.extend(await asyncio.gather(*pending, return_exceptions=True))
            return results
        finally:
            self._sync_tasks.reset(token)
