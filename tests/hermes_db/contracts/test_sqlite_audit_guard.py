"""CPython's connection audit covers aliases, constructors, memory databases and URIs."""

import subprocess
import sys


def test_sqlite_audit_rejects_every_connection_entry_point(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1]) / 'blocked.db'
original = sqlite3.connect
calls = [(original, ':memory:'), (sqlite3.dbapi2.connect, ':memory:'),
         (sqlite3.Connection, ':memory:'), (original, path.as_uri() + '?mode=rwc')]
seen = []
def audit(event, args):
    if event == 'sqlite3.connect':
        seen.append(True)
        raise AssertionError('SQLite connection prohibited')
sys.addaudithook(audit)
for connect, location in calls:
    try:
        connection = connect(location, uri=True)
    except AssertionError as error:
        assert str(error) == 'SQLite connection prohibited'
    else:
        connection.close()
        raise RuntimeError('SQLite connection guard did not run')
assert len(seen) == len(calls) and not path.exists()
print('SQLITE_AUDIT_GUARD_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_AUDIT_GUARD_OK" in result.stdout
