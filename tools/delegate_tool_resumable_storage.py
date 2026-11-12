"""Capture and bind the selected owner for resumable delegation records."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PostgresLedgerRef:
    profile_home: Path
    store: Any = field(default=None, repr=False, compare=False)


def location_for_home(home):
    from hermes_cli.db_setup import storage_backend
    home = Path(home)
    return PostgresLedgerRef(home) if storage_backend(home) == "postgresql" else home / "state.db"


@contextmanager
def open_ledger(location):
    if isinstance(location, PostgresLedgerRef):
        from hermes_cli.db_setup import _owning_profile
        from hermes_cli.db_sessions import acquire_sessions
        from hermes_db.domains.runtime.postgres.resumable import PostgresResumableLedger
        from hermes_db.core.values import resource_key
        with _owning_profile(location.profile_home):
            store = location.store if location.store is not None else acquire_sessions(location.profile_home / "state.db")
            try:
                with store._write() as connection:
                    yield PostgresResumableLedger(connection, store.scope, resource_key(store._transactions))
            finally:
                if location.store is None:
                    store.close()
    else:
        from hermes_db.domains.runtime.resumable import SqliteResumableLedger
        from hermes_db.infra.sqlite.transactions import transaction
        from tools.async_delegation import open_state_db
        with transaction(open_state_db(location, "state.db (resumable_subagents)")) as connection:
            yield SqliteResumableLedger(connection)


def pin_rows(location, now, cap):
    if isinstance(location, PostgresLedgerRef):
        with open_ledger(location) as records:
            return records.pins(now, cap)
    import sqlite3
    from contextlib import closing
    from hermes_db.domains.runtime.resumable import SqliteResumableLedger
    from hermes_db.infra.sqlite.safe_read import connect_tracked
    from hermes_state_holders import read_only_db_uri
    try:
        with closing(connect_tracked(read_only_db_uri(location), tracking_path=location, uri=True, timeout=2.0)) as connection:
            return SqliteResumableLedger(connection).pins(now, cap)
    except sqlite3.Error:
        return []  # Native stores from before the explicit upgrade have no resumable table.
