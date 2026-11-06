"""Production store fixtures on an owned, real PostgreSQL test namespace."""

from dataclasses import replace

import pytest


@pytest.fixture
def pg_store(postgres_test_config, postgres_schema, tmp_path):
    from hermes_db.engine import get_engine
    from hermes_db.schema import upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.session_store import PostgresSessionStore
    from hermes_db.postgresql.transactions import Transactions

    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(settings)
    transactions = Transactions(get_engine(settings), settings.schema,
                                 lock_timeout=settings.write_lock_timeout_seconds,
                                 statement_timeout=settings.statement_timeout_seconds)
    store = PostgresSessionStore(transactions, DatabaseScope(tmp_path, "contract-store"))
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def pg_runtime(pg_store):
    from hermes_db.runtime_store import PostgresRuntimeStore
    return PostgresRuntimeStore(pg_store)
