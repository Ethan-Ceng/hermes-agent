"""Observe Core DML on one connection while a worker handler runs.

Journal writes are outside the observation: a read receipt must not change the
session's client-visible revision merely because it persisted its result.
"""

from contextlib import contextmanager

from sqlalchemy import event


@contextmanager
def track_changes(connection):
    state = {"changed": False}

    def after_execute(conn, statement, multiparams, params, execution_options, result):
        if not getattr(statement, "is_dml", False):
            return
        count = result.rowcount
        # SQLite's RETURNING cursor reports zero before fetch. This is only
        # relevant to the offline harness; PG writes preserve driver row counts.
        returning_unknown = result.returns_rows and not conn.dialect.supports_sane_rowcount_returning
        if count != 0 or returning_unknown:
            state["changed"] = True

    event.listen(connection, "after_execute", after_execute)
    try:
        yield state
    finally:
        event.remove(connection, "after_execute", after_execute)
