"""Technical PostgreSQL resources do not load business or application modules."""

import subprocess
import sys


_PROBE = r'''
import importlib.abc
import sys

class InfrastructureOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('hermes_db.domains', 'hermes_db.tables', 'hermes_db.integration',
                                'hermes_db.core', 'hermes_cli', 'gateway', 'agent')):
            raise AssertionError('Infrastructure selected a business or application module')

sys.meta_path.insert(0, InfrastructureOnly())
from hermes_db.infra.postgresql.engine import get_engine, close_engines
from hermes_db.infra.postgresql.transactions import Transactions
from hermes_db.settings import PostgresSettings
settings = PostgresSettings('postgresql://unused/infra_probe', 'infra_probe')
first = get_engine(settings)
assert get_engine(settings) is first
Transactions(first, settings.schema, schema_token='independent_schema')
assert close_engines() == 1
second = get_engine(settings)
assert second is not first
assert close_engines() == 1
assert close_engines() == 0
'''


def test_postgresql_pool_lifecycle_without_business_imports():
    result = subprocess.run([sys.executable, '-c', _PROBE], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


_SQLITE_PROBE = r'''
import importlib.abc
import json
import sys

class SQLiteInfrastructureOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic', 'hermes_cli', 'gateway', 'agent'}:
            raise AssertionError('SQLite infrastructure selected optional drivers or application services')
        if fullname.startswith(('hermes_db.domains', 'hermes_db.tables', 'hermes_db.integration')):
            raise AssertionError('SQLite infrastructure selected business persistence')

sys.meta_path.insert(0, SQLiteInfrastructureOnly())
from hermes_db.infra.sqlite.connections import open_db
from hermes_db.infra.sqlite.schema import initialize_database
from hermes_db.infra.sqlite.transactions import transaction
path, operation = sys.argv[1:]
if operation == 'write':
    connection = open_db(path, db_label='infra', journal_mode='delete')
    initialize_database(connection, lambda conn: conn.execute('CREATE TABLE probe(value TEXT)'))
    with transaction(connection, immediate=True) as connection:
        connection.execute('INSERT INTO probe VALUES (?)', ('durable',))
else:
    import sqlite3
    statements = []
    original_connect = sqlite3.connect
    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    sqlite3.connect = traced_connect
    connection = open_db(path, db_label='infra', journal_mode='delete')
    with transaction(connection) as connection:
        assert connection.execute('SELECT value FROM probe').fetchone()[0] == 'durable'
    assert not any(sql.lstrip().upper().startswith(('CREATE', 'ALTER', 'DROP')) for sql in statements)
print(json.dumps({'pid': __import__('os').getpid(), 'operation': operation}))
'''


def test_sqlite_infrastructure_persists_across_processes_without_application_or_pg_imports(tmp_path):
    import json
    path = tmp_path / 'infra.db'
    results = []
    for operation in ('write', 'read'):
        result = subprocess.run([sys.executable, '-c', _SQLITE_PROBE, str(path), operation],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    assert results[0]['pid'] != results[1]['pid']
