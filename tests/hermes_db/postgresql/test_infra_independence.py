"""Generic real PG transactions accept caller-owned schema tokens without business imports."""

from dataclasses import asdict, replace
import json
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


_PROBE = r'''
import importlib.abc
import json
import sys

class InfrastructureOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('hermes_db.domains', 'hermes_db.tables', 'hermes_db.integration',
                                'hermes_db.core', 'hermes_cli', 'gateway', 'agent')):
            raise AssertionError('Infrastructure selected business or application modules')

sys.meta_path.insert(0, InfrastructureOnly())
def reject_sqlite(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('SQLite connection forbidden in the PG process')
sys.addaudithook(reject_sqlite)

def probe():
    from sqlalchemy import Column, Integer, MetaData, Table, select
    from hermes_db.infra.backends.postgresql.engine import close_engines, get_engine
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.settings import PostgresSettings
    settings = PostgresSettings(**json.loads(sys.stdin.read()))
    token = 'caller_owned_schema'
    engine = get_engine(settings)
    metadata = MetaData(schema=token)
    table = Table('infra_probe', metadata, Column('value', Integer, primary_key=True))
    # Fixture-owned schema, explicit test setup; acquiring resources performs no DDL.
    with engine.begin() as connection:
        metadata.create_all(connection.execution_options(schema_translate_map={token: settings.schema}))
    transactions = Transactions(engine, settings.schema, schema_token=token)
    with transactions.write() as connection:
        connection.execute(table.insert().values(value=1))
    try:
        with transactions.write() as connection:
            connection.execute(table.insert().values(value=2))
            raise ValueError('rollback body')
    except ValueError:
        pass
    with transactions.read() as connection:
        assert connection.execute(select(table.c.value)).scalars().all() == [1]
    assert close_engines() == 1
    assert close_engines() == 0

try:
    probe()
except BaseException as error:
    print(json.dumps({'error_type': type(error).__name__}))
    sys.exit(1)
print(json.dumps({'committed': [1], 'rolled_back': [2], 'sqlite_connections': 0}))
'''


def test_generic_transactions_commit_and_rollback_without_business_imports(postgres_test_config, postgres_schema):
    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    result = subprocess.run([sys.executable, '-c', _PROBE], input=json.dumps(asdict(settings)),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {'committed': [1], 'rolled_back': [2], 'sqlite_connections': 0}
