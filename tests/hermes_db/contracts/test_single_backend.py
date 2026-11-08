"""SQLite public domains run and restart with PostgreSQL imports actively rejected."""

import json
from pathlib import Path
import subprocess
import sys
import pytest

from tests.hermes_db.single_backend_support import prepare_workspace, run


def test_sqlite_business_process_needs_no_postgresql_stack_or_service(tmp_path):
    from hermes_cli.config import atomic_config_write
    home = tmp_path / "one"
    home.mkdir()
    atomic_config_write(home / "config.yaml", {"storage": {"backend": "sqlite"}})
    prepare_workspace(home)
    written = run("sqlite", "write", [home])
    recovered = run("sqlite", "read", [home])
    assert written["pid"] != recovered["pid"]
    assert written["sqlite_connections"] > 0 and recovered["sqlite_connections"] > 0


@pytest.mark.platforms("linux")
def test_full_sqlite_business_including_actual_matrix_sdk_crypto_restarts_without_pg_service(tmp_path):
    from hermes_cli.config import atomic_config_write
    home = tmp_path / "one"
    home.mkdir()
    atomic_config_write(home / "config.yaml", {"storage": {"backend": "sqlite"}})
    prepare_workspace(home)
    written = run("sqlite", "write", [home], matrix=True)
    recovered = run("sqlite", "read", [home], matrix=True)
    assert written["pid"] != recovered["pid"]


def test_pg_guard_catches_memory_uri_alias_and_direct_constructor(tmp_path):
    code = r'''
import json, sqlite3, sys
alias = sqlite3.connect
from tests.hermes_db.single_backend_guard import install
attempts = install('postgresql', sys.argv[1])
for factory, args, kwargs in ((sqlite3.connect, (':memory:',), {}),
    (sqlite3.connect, ('file:acceptance?mode=memory&cache=shared',), {'uri': True}),
    (alias, (':memory:',), {}), (sqlite3.Connection, (':memory:',), {})):
    try:
        factory(*args, **kwargs)
    except AssertionError:
        continue
    raise AssertionError('SQLite guard missed a connection entry point')
assert len(attempts) == 4
print(json.dumps({'rejected': len(attempts)}))
'''
    root = Path(__file__).resolve().parents[3]
    witness = tmp_path / "attempt"
    result = subprocess.run([sys.executable, "-c", code, str(witness)], cwd=root, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["rejected"] == 4
    assert witness.read_text() == "SQLITE_CONNECTION_ATTEMPT"


def test_user_sqlite_document_remains_readable_in_a_separate_input_process(tmp_path):
    code = r'''
from contextlib import closing
import hashlib, sqlite3, sys
from pathlib import Path
from tools.read_extract import _extract_sqlite
path = Path(sys.argv[1])
with closing(sqlite3.connect(path)) as connection:
    connection.execute('CREATE TABLE document (content TEXT)')
    connection.execute('INSERT INTO document VALUES (?)', ('user file content',))
    connection.commit()
before = hashlib.sha256(path.read_bytes()).digest()
preview = _extract_sqlite(str(path))
assert 'user file content' in preview and '1 rows' in preview
assert hashlib.sha256(path.read_bytes()).digest() == before
print('USER_SQLITE_DOCUMENT_READ_ONLY_OK')
'''
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "document.db")], cwd=root,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "USER_SQLITE_DOCUMENT_READ_ONLY_OK" in result.stdout
