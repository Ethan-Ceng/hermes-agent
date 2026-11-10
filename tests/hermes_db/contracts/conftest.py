"""Shared business contracts: original SQLite and offline Core execution.

The Core SQLite harness is a unit-level SQLAlchemy check, never PostgreSQL
verification. Real PG executes the same contracts in postgresql/ separately.
"""

import pytest


@pytest.fixture
def unavailable_native(monkeypatch):
    from hermes_db.integration import registry as native_registry
    from hermes_db.errors import StorageUnavailableError
    def unavailable(*args):
        raise StorageUnavailableError('test storage unavailable')
    monkeypatch.setattr(native_registry, '_construct_store', unavailable)


def _offline_engine(sa, tmp_path, name):
    from sqlalchemy.sql.dml import Insert
    from hermes_db.tables.conversations import messages
    from hermes_db.tables.runtime import session_admissions
    from hermes_db.tables.metadata import SCHEMA

    engine = sa.create_engine(f"sqlite:///{tmp_path / name}").execution_options(schema_translate_map={SCHEMA: None})

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    @sa.event.listens_for(engine, "before_execute", retval=True)
    def offline_identity(conn, statement, multiparams, params, execution_options):
        # SQLite has no IDENTITY on a composite primary key. This harness-only
        # allocator enables sequential contracts; it proves no PG sequence or
        # concurrency behavior. Production never uses this hook.
        if isinstance(statement, Insert) and statement.table is messages and "id" not in statement.compile().params:
            if statement.select is not None:
                maximum = sa.select(sa.func.coalesce(sa.func.max(messages.c.id), 0)).correlate(None).scalar_subquery()
                projection = statement.select.add_columns(maximum + sa.func.row_number().over(order_by=messages.c.id))
                statement = sa.insert(messages).from_select([*statement._select_names, "id"], projection)
            else:
                row_id = conn.scalar(sa.select(sa.func.coalesce(sa.func.max(messages.c.id), 0) + 1))
                statement = statement.values(id=row_id)
        if isinstance(statement, Insert) and statement.table is session_admissions and "seq" not in statement.compile().params:
            sequence = conn.scalar(sa.select(sa.func.coalesce(sa.func.max(session_admissions.c.seq), 0) + 1))
            statement = statement.values(seq=sequence)
        return statement, multiparams, params

    return engine


@pytest.fixture(params=["sqlite", "core"])
def store(request, tmp_path):
    if request.param == "sqlite":
        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "reference.db") as db:
            yield db
        return
    sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_db.integration.session_composition import create_session_store
    from hermes_db.scope import DatabaseScope
    from hermes_db.tables import load_metadata
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA

    engine = _offline_engine(sa, tmp_path, "core.db")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        load_metadata().create_all(conn)
    try:
        store = create_session_store(Transactions(engine, schema=None, schema_token=SCHEMA), DatabaseScope(tmp_path, "contract-store"))
        yield store
        store.close()
    finally:
        engine.dispose()


@pytest.fixture
def core_pair(tmp_path):
    sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_db.integration.session_composition import create_session_store
    from hermes_db.scope import DatabaseScope
    from hermes_db.tables import load_metadata
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA

    engine = _offline_engine(sa, tmp_path, "isolated.db")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        load_metadata().create_all(conn)
    transactions = Transactions(engine, schema=None, schema_token=SCHEMA)
    stores = [create_session_store(transactions, DatabaseScope(tmp_path / store, store)) for store in ("one", "two")]
    try:
        yield stores
    finally:
        for store in stores:
            store.close()
        engine.dispose()


@pytest.fixture
def native_registry(core_pair, monkeypatch):
    from hermes_db.integration import registry as native_registry
    from hermes_db.integration.session_composition import create_session_store
    opened = []

    def construct(settings, scope):
        store = create_session_store(core_pair[0]._transactions, scope)
        opened.append(store)
        return store

    monkeypatch.setattr(native_registry, "_construct_store", construct)
    yield native_registry, opened
    native_registry.close_all()


@pytest.fixture
def runtime(store, tmp_path):
    from hermes_state import SessionDB
    if isinstance(store, SessionDB):
        from hermes_db.backends.sqlite.acquire import SQLiteRuntime
        from hermes_db.scope import DatabaseScope
        return SQLiteRuntime(store, DatabaseScope(tmp_path))
    from hermes_db.integration.runtime_composition import create_runtime_store
    return create_runtime_store(store)


@pytest.fixture
def api_owner(core_pair, monkeypatch):
    from types import SimpleNamespace
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import SessionAuthority
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.integration.runtime_composition import create_runtime_store
    db, other = core_pair
    home = db.scope.profile_home
    home.mkdir(parents=True)
    token = set_hermes_home_override(home)
    monkeypatch.setattr(SessionStore, "_open_session_db_for_active_scope", lambda self, **kw: db)
    store = SessionStore(home / "sessions", GatewayConfig())
    store._db = db
    runner = SimpleNamespace(session_store=store, _session_db=db, adapters={}, _draining=False,
        config=GatewayConfig(), _adapter_for_source=lambda source: None)
    runtime = create_runtime_store(db)
    epoch = runtime.begin_epoch(instance_id="api-owner")
    authority = SessionAuthority(runner, profile_id=str(home), instance_id="api-owner", db=db, epoch=epoch)
    runner.session_authority = authority
    try:
        yield authority, db, other
    finally:
        reset_hermes_home_override(token)
