"""The optional storage stack must not become a SQLite startup dependency."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_postgresql_extra_has_a_synchronous_core_driver():
    sqlalchemy = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    psycopg = pytest.importorskip("psycopg", reason="optional postgresql extra")
    pytest.importorskip("alembic", reason="optional postgresql extra")
    # Engine creation loads the DBAPI but must not open a network connection.
    engine = sqlalchemy.create_engine("postgresql+psycopg://localhost/unused")
    try:
        assert engine.dialect.dbapi is psycopg
        assert not engine.dialect.is_async
    finally:
        engine.dispose()


def test_sqlite_works_when_postgresql_imports_are_unavailable(tmp_path):
    script = """
import importlib.abc
import sys
from pathlib import Path

class WithoutPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic'}:
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, WithoutPostgres())
import hermes_db
from hermes_state import SessionDB
from hermes_db.integration.runtime_access import runtime_for_store
with SessionDB(db_path=Path(sys.argv[1])) as db:
    db.create_session('sqlite-only', source='cli')
    db.append_message('sqlite-only', role='user', content='preserved')
    assert db.get_messages('sqlite-only')[0]['content'] == 'preserved'
    runtime = runtime_for_store(db)
    epoch = runtime.begin_epoch(instance_id='sqlite-only')
    accepted = runtime.admit_input(epoch=epoch, principal_id='human', session_id='sqlite-only',
        request_id='one', payload={'text': 'ask'})
    claimed = runtime.claim_input(epoch=epoch, session_id='sqlite-only')
    assert claimed['admission_id'] == accepted['admission_id']
    assert runtime.settle_input(epoch=epoch, admission_id=accepted['admission_id'],
        generation=claimed['generation'], outcome='completed')['status'] == 'terminal'
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "state.db")],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "HERMES_HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
