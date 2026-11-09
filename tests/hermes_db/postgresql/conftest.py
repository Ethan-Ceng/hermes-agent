"""Production store fixtures on an owned, real PostgreSQL test namespace."""

from dataclasses import replace

import pytest


@pytest.fixture
def pg_store(postgres_test_config, postgres_schema, tmp_path):
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.schema import upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.integration.session_composition import create_session_store
    from hermes_db.backends.postgresql.transactions import Transactions

    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(settings)
    transactions = Transactions(get_engine(settings), settings.schema,
                                 lock_timeout=settings.write_lock_timeout_seconds,
                                 statement_timeout=settings.statement_timeout_seconds)
    store = create_session_store(transactions, DatabaseScope(tmp_path, "contract-store"))
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def pg_runtime(pg_store):
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
    return PostgresRuntimeStore(pg_store)


@pytest.fixture
def pg_pair(pg_store, tmp_path):
    from hermes_db.scope import DatabaseScope
    from hermes_db.integration.session_composition import create_session_store
    peer = create_session_store(pg_store._transactions, DatabaseScope(tmp_path / "other", "other-store"))
    try:
        yield [pg_store, peer]
    finally:
        peer.close()


@pytest.fixture(autouse=True)
def pg_sqlite_guard(monkeypatch):
    """Reject aliases/direct constructors as well as connect(), even when a caller catches errors."""
    import sqlite3
    import sys
    attempts = []
    enabled = [True]
    def reject(*args, **kwargs):
        attempts.append(True)
        pytest.fail("PG domain business process must reject every SQLite connection")
    def audit(event, args):
        if enabled[0] and event == "sqlite3.connect":
            reject()
    sys.addaudithook(audit)
    monkeypatch.setattr(sqlite3, "connect", reject)
    try:
        yield
    finally:
        enabled[0] = False
        assert not attempts, "PG business code attempted SQLite, even if its caller caught the rejection"


@pytest.fixture
def pg_profiles(postgres_test_config, postgres_schema, tmp_path, monkeypatch, pg_sqlite_guard):
    """Actual Profile configuration for domain consumers; forbids every SQLite connection."""
    from contextlib import contextmanager
    import json
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_cli.config import atomic_config_write
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.schema import upgrade_schema

    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)

    @contextmanager
    def owner(name):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": {
            "schema": pg.schema, "store_id": name, "pool_size": 2, "max_overflow": 0, "connection_budget": 2}}})
        (home / ".env").write_text("HERMES_POSTGRES_DSN=" + json.dumps(pg.dsn) + "\n", encoding="utf-8")
        home_token = set_hermes_home_override(home)
        secret_token = set_secret_scope({"HERMES_POSTGRES_DSN": pg.dsn}, profile_home=str(home))
        try:
            yield home
        finally:
            reset_secret_scope(secret_token)
            reset_hermes_home_override(home_token)

    yield owner
