"""SQLite connections configured from explicit technical options; opening never runs business DDL."""
from __future__ import annotations

import sqlite3
import time
from functools import partial
from pathlib import Path

def _connect_create(path: Path | str, **options) -> sqlite3.Connection:
    if str(path) == ":memory:":
        return sqlite3.connect(":memory:", **options)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, **options)


def open_db(path: Path | str, **options) -> sqlite3.Connection:
    """Open an explicitly creatable SQLite file with the selected connection policy."""
    return _open_configured(partial(_connect_create, path), **options)


def open_existing_db(path: Path | str, **options) -> sqlite3.Connection:
    """Open an existing file without creating a database when the path vanishes."""
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    return _open_configured(partial(sqlite3.connect, uri, uri=True), **options)


def _open_configured(
    connect,
    *,
    db_label: str,
    busy_timeout_ms: int = 5000,
    wal: bool = True,
    foreign_keys: bool = False,
    synchronous_full: bool = False,
    row_factory=sqlite3.Row,
    check_same_thread: bool = True,
    wal_lock_retries: int = 1,
    journal_mode: str = "wal",
    repair_hint: str = "upgrade the linked SQLite runtime",
) -> sqlite3.Connection:
    """Apply the selected PRAGMAs and close the connection if configuration fails.

    ``busy_timeout_ms`` is the single busy knob: it is passed as ``connect(timeout=)`` AND set as the
    explicit PRAGMA so it is observable. ``wal=True`` goes through ``apply_wal_with_fallback`` — the
    only journal-mode setter that carries the WAL-reset-bug gate, the network-FS silent-refusal
    fallback and the never-live-downgrade invariant; a raw ``PRAGMA journal_mode=WAL`` bypasses all
    three. Only the transient ``database is locked`` from that pragma is retried (``wal_lock_retries``):
    a first opener initializing a shared DB can make it ignore the busy timeout, notably on Windows.
    """
    from hermes_db.infra.backends.sqlite.wal import apply_wal_with_fallback

    # Resolved at call time: fd-leak tests patch ``sqlite3.connect`` through the caller's module.
    conn = connect(timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread)
    try:
        conn.row_factory = row_factory
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        if wal:
            for attempt in range(wal_lock_retries):
                try:
                    apply_wal_with_fallback(conn, db_label=db_label, journal_mode=journal_mode, repair_hint=repair_hint)
                    break
                except sqlite3.OperationalError as exc:
                    if str(exc).lower() != "database is locked" or attempt + 1 == wal_lock_retries:
                        raise
                    time.sleep(0.01 * (2**attempt))
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        if synchronous_full:
            conn.execute("PRAGMA synchronous=FULL")
    except BaseException:
        conn.close()
        raise
    return conn


def open_uri(uri: str, **options) -> sqlite3.Connection:
    """Open an already-resolved SQLite URI while retaining actual file-connection tracking."""
    from hermes_db.infra.backends.sqlite.safe_read import connect_tracked
    return _open_configured(partial(connect_tracked, uri, uri=True), **options)
