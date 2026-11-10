"""Durable state for Discord reconnect message recovery."""

from __future__ import annotations

import datetime as dt
import logging
import os
import sqlite3
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from hermes_constants import get_hermes_home
from .recovery_protocol import RecoveryOperations

logger = logging.getLogger(__name__)

_DB_FILENAME = "discord_message_recovery.db"
_RETENTION_DAYS = 30


class DiscordRecoveryStore(RecoveryOperations):
    """Small profile-scoped SQLite ledger for completed Discord messages."""

    def __init__(self, hermes_home: Path | None = None) -> None:
        from hermes_cli.db_setup import storage_backend
        self._backend = None
        if storage_backend(hermes_home) == "postgresql":
            from hermes_db.domains.plugin_storage.discord.postgres.store import PostgresDiscordRecoveryStore
            self._backend = PostgresDiscordRecoveryStore(hermes_home)
            self.reference = self._backend.reference
            return
        self._lock = threading.Lock()
        self._initialized = False
        self._hermes_home = Path(hermes_home or get_hermes_home())

    def path(self) -> Path:
        if self._backend is not None:
            return self._backend.path()
        directory = self._hermes_home / "gateway"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / _DB_FILENAME

    def call(self, fn: Callable[[sqlite3.Connection], Any], default: Any = None) -> Any:
        if self._backend is not None:
            return self._backend.call(fn, default)
        from hermes_cli.db_setup import storage_backend
        from hermes_db.errors import StorageConfigurationError
        if storage_backend(self._hermes_home) != "sqlite":
            raise StorageConfigurationError("Selected PG Discord recovery cannot open a private SQLite connection")
        try:
            with self._lock:
                path = self.path()
                conn = sqlite3.connect(path, timeout=0.1)
                try:
                    if not self._initialized:
                        self._initialize(conn)
                        conn.commit()
                        self._initialized = True
                        with suppress(OSError):
                            os.chmod(path, 0o600)
                    result = fn(conn)
                    conn.commit()
                    return result
                finally:
                    conn.close()
        except Exception as exc:
            logger.warning("Discord recovery ledger unavailable: %s", exc)
            return default

    def _operation(self, name, *, default=None, **fields):
        if self._backend is not None:
            return self._backend._operation(name, default=default, **fields)
        from . import recovery_sqlite
        from plugins.plugin_storage import plugin_sqlite_transaction as write_txn
        def invoke(conn):
            with write_txn(conn):
                return getattr(recovery_sqlite, name)(conn, **fields)
        return self.call(invoke, default)

    def _initialize(self, conn: sqlite3.Connection) -> None:
        from plugins.plugin_storage import configure_plugin_sqlite as apply_wal_with_fallback
        apply_wal_with_fallback(conn, db_label="discord_recovery.db")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS discord_messages (
                message_id TEXT PRIMARY KEY, channel_id TEXT, thread_id TEXT, parent_channel_id TEXT,
                author_id TEXT, created_at TEXT, status TEXT NOT NULL,
                replied INTEGER NOT NULL DEFAULT 0, emoji_ack INTEGER NOT NULL DEFAULT 0,
                outage_response INTEGER NOT NULL DEFAULT 0, response_message_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT, last_error TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS discord_recovery_scans (
                scan_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
                channels TEXT NOT NULL, window_seconds REAL NOT NULL, limit_count INTEGER NOT NULL,
                scanned INTEGER NOT NULL DEFAULT 0, missed INTEGER NOT NULL DEFAULT 0,
                dispatched INTEGER NOT NULL DEFAULT 0, error TEXT
            );
            CREATE TABLE IF NOT EXISTS discord_recovery_cursors (
                channel_id TEXT PRIMARY KEY, last_message_id TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=_RETENTION_DAYS)).isoformat()
        conn.execute("DELETE FROM discord_messages WHERE updated_at < ?", (cutoff,))
        conn.execute("DELETE FROM discord_recovery_scans WHERE COALESCE(completed_at, started_at) < ?", (cutoff,))
        conn.execute("DELETE FROM discord_recovery_cursors WHERE updated_at < ?", (cutoff,))
