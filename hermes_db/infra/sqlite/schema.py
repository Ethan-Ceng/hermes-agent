"""Explicit SQLite Schema execution; business callers own DDL and version algorithms."""
from __future__ import annotations

import sqlite3

def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE <table> ADD COLUMN <ddl>``, idempotent across races: True when this call added
    it, False on the ``duplicate column name`` a concurrent migrator caused.

    ``column`` is the human-readable name for the call site; ``ddl`` carries the actual definition. See
    #21708.
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        return True
    except sqlite3.OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            return False
        raise



def initialize_database(conn, initialize):
    """Run an explicit business initialization, retaining failure-close ownership."""
    try:
        initialize(conn)
    except BaseException:
        conn.close()
        raise
    return conn
