"""Short Core connections and transaction phases; no blind write retries."""

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeout

from hermes_db.errors import (
    RetryableStorageError, StorageBusyError, StorageConflictError, StorageQueryTimeoutError, StorageUnavailableError,
    StorageWriteError, UnknownCommitError,
)


class Transactions:
    def __init__(self, engine, schema, *, schema_token, lock_timeout=10, statement_timeout=60):
        self.engine = engine
        self.schema = schema
        self.schema_token = schema_token
        self.lock_timeout = lock_timeout
        self.statement_timeout = statement_timeout

    def _timeouts(self, conn, lock_timeout=None):
        if conn.dialect.name == "postgresql":
            timeout = self.lock_timeout if lock_timeout is None else lock_timeout
            conn.execute(text("SELECT set_config('lock_timeout', :lock_timeout, true), "
                              "set_config('statement_timeout', :statement_timeout, true)"),
                         {"lock_timeout": str(max(1, int(timeout * 1000))),
                          "statement_timeout": str(max(1, int(self.statement_timeout * 1000)))})

    @contextmanager
    def read(self):
        try:
            with self.engine.connect() as conn:
                if conn.dialect.name == "postgresql":
                    conn = conn.execution_options(isolation_level="REPEATABLE READ")
                self._timeouts(conn)
                yield conn.execution_options(schema_translate_map={self.schema_token: self.schema})
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise StorageQueryTimeoutError("Session database query deadline exceeded") from None
            raise StorageUnavailableError("Session database read unavailable") from None
        except PoolTimeout:
            raise StorageUnavailableError("Session database pool wait timed out") from None

    @contextmanager
    def write(self, *, lock_timeout=None):
        phase = "connect"
        try:
            with self.engine.begin() as conn:
                phase = "body"
                self._timeouts(conn, lock_timeout=lock_timeout)
                # INSERT counts feed repair totals and worker no-op tracking.
                yield conn.execution_options(schema_translate_map={self.schema_token: self.schema}, preserve_rowcount=True)
                phase = "commit"
        except IntegrityError:
            raise StorageConflictError("Session storage constraint conflict") from None
        except PoolTimeout:
            raise StorageUnavailableError("Session database pool wait timed out") from None
        except DBAPIError as error:
            state = getattr(error.orig, "sqlstate", None)
            if state in ("40001", "40P01"):
                raise RetryableStorageError("Session transaction rolled back due to contention") from None
            if phase == "commit":
                raise UnknownCommitError("Session commit outcome is unknown; inspect the original request receipt") from None
            if phase == "connect":
                raise StorageUnavailableError("Session database connection unavailable") from None
            if state == "55P03":
                raise StorageBusyError("Session database lock wait timed out") from None
            raise StorageWriteError("Session database write failed") from None
