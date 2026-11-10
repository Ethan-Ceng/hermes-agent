"""Transaction phase errors must not turn unknown commits into blind retries."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")

from hermes_db.errors import RetryableStorageError, StorageBusyError, StorageConflictError, StorageWriteError, UnknownCommitError
from hermes_db.infra.backends.postgresql.transactions import Transactions
from hermes_db.tables.metadata import SCHEMA


class DriverFailure(Exception):
    def __init__(self, state):
        super().__init__("private connection details")
        self.sqlstate = state


class Connection:
    dialect = SimpleNamespace(name="sqlite")

    def execution_options(self, **kwargs):
        return self


class FailingEngine:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error
        self.closed = False

    @contextmanager
    def begin(self):
        try:
            yield Connection()
            if self.commit_error:
                raise self.commit_error
        finally:
            self.closed = True


@pytest.mark.parametrize("state", [None, "08006", "57014", "55P03"])
def test_commit_failure_is_unknown_and_body_is_not_replayed(state):
    engine = FailingEngine(sa.exc.OperationalError(None, None, DriverFailure(state)))
    transactions = Transactions(engine, schema="hermes", schema_token=SCHEMA)
    writes = []
    with pytest.raises(UnknownCommitError) as error:
        with transactions.write():
            writes.append("write")
    assert writes == ["write"]
    assert engine.closed
    assert "private connection details" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("state", ["40001", "40P01"])
def test_confirmed_rollback_is_distinct_from_an_unknown_commit(state):
    engine = FailingEngine(sa.exc.OperationalError(None, None, DriverFailure(state)))
    with pytest.raises(RetryableStorageError):
        with Transactions(engine, schema="hermes", schema_token=SCHEMA).write():
            pass
    assert engine.closed


def test_body_and_constraint_failures_close_the_connection():
    engine = FailingEngine()
    with pytest.raises(StorageWriteError):
        with Transactions(engine, schema="hermes", schema_token=SCHEMA).write():
            raise sa.exc.OperationalError(None, None, DriverFailure("22000"))
    assert engine.closed
    with pytest.raises(StorageConflictError):
        with Transactions(engine, schema="hermes", schema_token=SCHEMA).write():
            raise sa.exc.IntegrityError(None, None, DriverFailure("23505"))


def test_lock_timeout_is_retryable_only_after_body_rollback():
    engine = FailingEngine()
    with pytest.raises(StorageBusyError) as error:
        with Transactions(engine, schema="hermes", schema_token=SCHEMA).write(lock_timeout=0.01):
            raise sa.exc.OperationalError(None, None, DriverFailure("55P03"))
    assert engine.closed
    assert "private connection details" not in str(error.value)
