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
from hermes_db.infra.backends.postgresql.engine import get_engine, close_engines
from hermes_db.infra.backends.postgresql.transactions import Transactions
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
