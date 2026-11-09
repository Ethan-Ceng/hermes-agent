"""Selected PG Discord store refuses raw SQLite callbacks and never returns empty on outage."""

import datetime as dt
import threading
from hermes_db.domains.plugin_storage.discord.api import capture_discord, open_discord
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.plugin_storage.discord.postgres.operations import recovery as operations
from hermes_db.domains.plugin_storage.discord.postgres.queries.recovery import lock_store

READS = frozenset({"probe", "is_complete", "active_claim", "attempts_exhausted", "cursor"})


class PostgresDiscordRecoveryStore:
    def __init__(self, hermes_home=None):
        self.reference = capture_discord(hermes_home)
        self._hermes_home = self.reference.profile_home
        self._lock, self._initialized = threading.Lock(), False

    def path(self):
        raise StorageConfigurationError("PG Discord recovery has no SQLite database path")

    def call(self, fn, default=None):
        raise StorageConfigurationError("PG Discord recovery exposes named operations, not SQLite Connection callbacks")

    def _initialize(self):
        with self._lock:
            if not self._initialized:
                cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=30)).isoformat()
                with open_discord(self.reference, write=True) as conn:
                    lock_store(conn, self.reference)
                    operations.prune(conn, self.reference, cutoff=cutoff)
                self._initialized = True

    def _operation(self, name, *, default=None, **fields):
        self._initialize()
        with open_discord(self.reference, write=name not in READS) as conn:
            if name not in READS:
                lock_store(conn, self.reference)
            return getattr(operations, name)(conn, self.reference, **fields)
