"""Shared leaf helpers for the gateway hosted-room modules.

Each hosted-room module validates identifiers, bounded integers, exact field sets and
canonical JSON with its own error class and pinned error strings; these helpers take the
error class and message templates as parameters so failures stay byte-identical while the
logic lives once. Must stay a leaf: never import a hosted_room* module (import cycle).
"""

from __future__ import annotations

from hermes_cli.db_sqlite_policy import initialize_profile_sqlite

import json
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from hermes_db.domains.rooms.api import RoomStoreRef


DbPath = Path | str | RoomStoreRef




















def open_sqlite(path: DbPath, *, timeout: float = 10) -> sqlite3.Connection:
    """Row-factory connection with foreign keys on; no journal or schema work (steady-state readers)."""
    from hermes_cli.db_sqlite_policy import open_profile_sqlite as open_db

    return open_db(path, db_label="shared-state.db", busy_timeout_ms=int(timeout * 1000), wal=False,
                   foreign_keys=True)


def connect(
    db_path: DbPath, *, db_label: str, ready: Callable[[sqlite3.Connection], bool],
    initialize: Callable[[sqlite3.Connection], None], lock_retries: int = 1) -> sqlite3.Connection:
    """Open the shared root store: WAL, foreign keys, then ``initialize`` in one IMMEDIATE txn if not ``ready``.

    Multiple profile gateways share this database, so every draft-schema transition
    is serialized in SQLite itself: a crash rolls back the whole DDL/data migration and
    another process can safely retry it.
    """
    def _initialize(conn: sqlite3.Connection) -> None:
        if not ready(conn):
            try:
                conn.execute("BEGIN IMMEDIATE")
                initialize(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    # Late import: a gateway that outlives an on-disk upgrade has the OLD sqlite_util cached.
    from hermes_cli.db_sqlite_policy import open_profile_sqlite as open_db

    return initialize_profile_sqlite(db_path, db_label=db_label, busy_timeout_ms=10_000, foreign_keys=True,
                   wal_lock_retries=lock_retries, initialize=_initialize)


def fenced_update(conn: sqlite3.Connection, sql: str, params: tuple, error: Exception) -> None:
    """Run a compare-and-swap UPDATE; anything but exactly one row means the fence was lost."""
    if conn.execute(sql, params).rowcount != 1:
        raise error


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))


def transaction(
    connect: Callable[[DbPath], sqlite3.Connection], db_path: DbPath, *, immediate: bool
) -> Iterator[sqlite3.Connection]:
    """Open via ``connect``, optionally ``BEGIN IMMEDIATE``, commit on success, always close."""
    from hermes_db.infra.backends.sqlite.transactions import transaction as _transaction

    return _transaction(connect(db_path), immediate=immediate)
