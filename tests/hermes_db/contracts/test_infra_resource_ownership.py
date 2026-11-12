"""Resolved backend resources need no application or business-store imports."""

import json
import subprocess
import sys


def test_sqlite_selection_and_fresh_process_recovery_without_application_or_pg(tmp_path):
    code = r'''
import importlib.abc
import json
import os
import sys
from pathlib import Path
class InfrastructureOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'hermes_cli', 'hermes_state', 'agent', 'gateway', 'sqlalchemy', 'psycopg', 'alembic'} or fullname.startswith(('hermes_state', 'hermes_db.domains', 'hermes_db.tables', 'hermes_db.integration')):
            raise AssertionError('Backend selection imported application, business or PG code')
sys.meta_path.insert(0, InfrastructureOnly())
from hermes_db.factory import acquire_backend
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings
from hermes_db.infra.sqlite.connections import open_db
path = Path(sys.argv[1])
resource = acquire_backend(DatabaseSettings(), DatabaseScope(path.parent), sqlite_path=path)
assert resource.sqlite_path == path
assert not hasattr(resource, 'sessions') and not hasattr(resource, 'runtime')
conn = open_db(resource.sqlite_path, db_label='isolated-contract', wal=False)
try:
    if sys.argv[2] == 'write':
        conn.execute('CREATE TABLE selected_data(value TEXT NOT NULL)')
        conn.execute('INSERT INTO selected_data VALUES (?)', ('durable selection',))
        conn.commit()
    assert conn.execute('SELECT value FROM selected_data').fetchone()[0] == 'durable selection'
finally:
    conn.close()
print(json.dumps({'pid': os.getpid()}))
'''
    results = []
    for mode in ('write', 'read'):
        result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'selected.db'), mode],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    assert results[0]['pid'] != results[1]['pid']
