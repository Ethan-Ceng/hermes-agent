"""A concrete SQLite connection resource works independently of SessionDB and application imports."""

import subprocess
import sys


def test_pool_reads_real_data_and_closes_a_reader_returned_after_shutdown(tmp_path):
    code = r'''
import importlib.abc
import sqlite3
import sys
from pathlib import Path

class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'hermes_state', 'hermes_cli', 'agent', 'gateway', 'sqlalchemy', 'psycopg', 'alembic'}:
            raise AssertionError('Connection resource selected application or PostgreSQL imports')

sys.meta_path.insert(0, NoApplication())
from hermes_db.infra.backends.sqlite.session_connections import SQLiteConnections
path = Path(sys.argv[1])
writer = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
writer.execute('PRAGMA journal_mode=WAL')
writer.execute('CREATE TABLE values_table(value TEXT)')
writer.execute('INSERT INTO values_table VALUES (?)', ('persisted',))
resource = SQLiteConnections(path, read_only=False, read_uri=path.resolve().as_uri() + '?mode=ro',
                             pragmas={}, creation_site='independent-contract', capture_retired=None,
                             replaced_message='replaced', deleted_message='deleted')
resource.attach_writer(writer, wal_active=writer.execute('PRAGMA journal_mode').fetchone()[0] == 'wal')
with resource.pooled_read() as reader:
    assert reader is not None
    assert reader.execute('SELECT value FROM values_table').fetchone()[0] == 'persisted'
    resource.close()
    assert reader.execute('SELECT value FROM values_table').fetchone()[0] == 'persisted'
try:
    reader.execute('SELECT 1')
except sqlite3.ProgrammingError:
    pass
else:
    raise AssertionError('Reader returned after shutdown was leaked')
assert resource._read_budget.acquire(resource)
resource._read_budget.release()
resource.close()
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'pool.db')],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
