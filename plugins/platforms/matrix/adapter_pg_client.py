"""PG sync waits for SDK handlers and propagates durable-storage failures to its checkpoint."""

from mautrix.client import Client
from hermes_cli.db_setup import _owning_profile
from hermes_db.errors import StorageError


class PostgresMatrixClient(Client):
    def __init__(self, *args, profile_home, **kwargs):
        super().__init__(*args, **kwargs)
        self._profile_home = profile_home

    async def _catch_errors(self, handler, data):
        with _owning_profile(self._profile_home):
            try:
                await handler(data)
            except StorageError:
                raise
            except Exception:
                self.log.exception("Failed to run Matrix handler")

    def dispatch_manual_event(self, event_type, data, include_global_handlers=False, force_synchronous=False, source=None):
        return super().dispatch_manual_event(event_type, data, include_global_handlers=include_global_handlers,
            force_synchronous=True, source=source)
