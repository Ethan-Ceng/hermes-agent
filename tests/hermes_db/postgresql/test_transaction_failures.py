"""Real PG transaction failures retain typed outcomes and committed receipts."""

from dataclasses import replace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_acknowledgement_loss_after_real_commit_reuses_the_admission(pg_store, pg_runtime, monkeypatch):
    import psycopg
    from hermes_db.errors import UnknownCommitError
    pg_store.create_session('s', 'cli')
    epoch = pg_runtime.begin_epoch(instance_id='owner')
    args = dict(epoch=epoch, principal_id='human', session_id='s', request_id='once', payload={'text': 'once'})
    dialect = pg_store._transactions.engine.dialect
    original = dialect.do_commit

    def lose_ack(connection):
        original(connection)
        raise psycopg.OperationalError('injected commit acknowledgement loss')

    with monkeypatch.context() as patch:
        patch.setattr(dialect, 'do_commit', lose_ack)
        with pytest.raises(UnknownCommitError):
            pg_runtime.admit_input(**args)
    committed = pg_runtime.list_admissions(session_id='s')
    assert len(committed) == 1
    retry = pg_runtime.admit_input(**args)
    assert retry['admission_id'] == committed[0]['admission_id']
    assert len(pg_runtime.list_admissions(session_id='s')) == 1


def test_real_root_lock_timeout_does_not_partially_admit(pg_store, pg_runtime):
    from hermes_db.errors import StorageBusyError
    from hermes_db.backends.postgresql.transactions import Transactions
    from hermes_db.domains.sessions.postgres.queries import sessions
    from hermes_db.runtime_store import PostgresRuntimeStore
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore
    base = pg_store._transactions
    contender = PostgresSessionStore(Transactions(base.engine, base.schema, lock_timeout=0.05), pg_store.scope)
    try:
        runtime = PostgresRuntimeStore(contender)
        pg_store.create_session('s', 'cli')
        epoch = pg_runtime.begin_epoch(instance_id='owner')
        with base.write() as owner:
            sessions.lock_session(owner, pg_store.scope, 's')
            with pytest.raises(StorageBusyError):
                runtime.admit_input(epoch=epoch, principal_id='human', session_id='s', request_id='blocked', payload={})
        assert pg_runtime.list_admissions(session_id='s') == []
        assert pg_store.get_messages('s') == []
    finally:
        contender.close()


def test_real_statement_cancellation_is_a_query_timeout(pg_store):
    from sqlalchemy import text
    from hermes_db.errors import StorageQueryTimeoutError
    from hermes_db.backends.postgresql.transactions import Transactions
    base = pg_store._transactions
    transactions = Transactions(base.engine, base.schema, statement_timeout=0.05)
    with pytest.raises(StorageQueryTimeoutError), transactions.read() as conn:
        conn.execute(text('SELECT pg_sleep(5)'))


def test_closed_real_connection_is_storage_unavailable(pg_store):
    from sqlalchemy import text
    from hermes_db.errors import StorageUnavailableError
    with pytest.raises(StorageUnavailableError), pg_store._transactions.read() as conn:
        conn.connection.driver_connection.close()
        conn.execute(text('SELECT 1'))


def test_real_single_connection_pool_exhaustion_is_storage_unavailable(pg_store, postgres_test_config):
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.backends.postgresql.transactions import Transactions
    settings = replace(postgres_test_config.settings, schema=pg_store._transactions.schema,
        pool_size=1, max_overflow=0, connection_budget=1, pool_timeout_seconds=0.05)
    engine = get_engine(settings)
    try:
        with engine.connect(), pytest.raises(StorageUnavailableError), Transactions(engine, settings.schema).read():
            raise AssertionError('An exhausted pool must reject acquisition')
    finally:
        engine.dispose()
