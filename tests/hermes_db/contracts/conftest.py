"""Shared business contracts: original SQLite and offline Core execution.

The Core SQLite harness is a unit-level SQLAlchemy check, never PostgreSQL
verification. Real PG executes the same contracts in postgresql/ separately.
"""

import pytest


@pytest.fixture(params=["sqlite", "core"])
def store(request, tmp_path):
    if request.param == "sqlite":
        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "reference.db") as db:
            yield db
        return
    sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_db.session_store import PostgresSessionStore
    from hermes_db.scope import DatabaseScope
    from hermes_db.tables import load_metadata
    from hermes_db.tables.metadata import SCHEMA
    from hermes_db.postgresql.transactions import Transactions

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'core.db'}").execution_options(schema_translate_map={SCHEMA: None})
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        load_metadata().create_all(conn)
    try:
        store = PostgresSessionStore(Transactions(engine, schema=None), DatabaseScope(tmp_path, "contract-store"))
        yield store
        store.close()
    finally:
        engine.dispose()


@pytest.fixture
def core_pair(tmp_path):
    sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_db.session_store import PostgresSessionStore
    from hermes_db.scope import DatabaseScope
    from hermes_db.tables import load_metadata
    from hermes_db.tables.metadata import SCHEMA
    from hermes_db.postgresql.transactions import Transactions

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'isolated.db'}").execution_options(schema_translate_map={SCHEMA: None})
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        load_metadata().create_all(conn)
    transactions = Transactions(engine, schema=None)
    stores = [PostgresSessionStore(transactions, DatabaseScope(tmp_path / store, store)) for store in ("one", "two")]
    try:
        yield stores
    finally:
        for store in stores:
            store.close()
        engine.dispose()
