"""Explicit API SQLite creation and ordinary no-DDL opens preserve actual persistence."""
import os
import re
import sqlite3
import subprocess
import sys

import pytest


def test_api_existing_opens_have_no_ddl_and_restore_in_new_process(tmp_path, monkeypatch):
    from gateway.platforms.api_server_response_store import ResponseStore
    from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore

    response_path, run_path = tmp_path / 'response.db', tmp_path / 'runs.db'
    ResponseStore(db_path=str(response_path)).close()
    RunIdempotencyStore(db_path=str(run_path)).close()
    statements = []
    original = sqlite3.connect

    def traced(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlite3, 'connect', traced)
    responses = ResponseStore.open_existing(db_path=response_path)
    runs = RunIdempotencyStore.open_existing(db_path=run_path)
    try:
        responses.put('response', {'text': '值\x00🙂'})
        assert responses.get('response') == {'text': '值\x00🙂'}
        outcome, _row = runs.reserve('scope', 'key', 'digest', 'run', {'status': 'completed'})
        assert outcome == 'created'
    finally:
        responses.close()
        runs.close()
    assert statements
    assert not [sql for sql in statements if re.match(r'\s*(CREATE|ALTER|DROP)\b', sql, re.IGNORECASE)]
    code = """
import os,sys
from gateway.platforms.api_server_response_store import ResponseStore
from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
responses=ResponseStore.open_existing(db_path=sys.argv[1])
runs=RunIdempotencyStore.open_existing(db_path=sys.argv[2])
try:
    assert responses.get('response') == {'text':'值\\x00🙂'}
    outcome,row=runs.lookup('scope','key','digest')
    assert outcome == 'reused' and row['run_id'] == 'run'
    assert os.getpid() != int(sys.argv[3])
finally:
    responses.close()
    runs.close()
"""
    child = subprocess.run([sys.executable, '-c', code, str(response_path), str(run_path), str(os.getpid())],
        env=dict(os.environ, HERMES_HOME=str(tmp_path), HERMES_RUNTIME_DIR=str(tmp_path / 'child-runtime')),
        capture_output=True, text=True, timeout=30, check=False)
    assert child.returncode == 0, child.stderr


def test_missing_api_schema_is_not_created_by_ordinary_open(tmp_path):
    from gateway.platforms.api_server_response_store import ResponseStore
    from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
    from hermes_db.errors import StorageSchemaError

    for store, name in [(ResponseStore, 'responses.db'), (RunIdempotencyStore, 'runs.db')]:
        path = tmp_path / name
        with pytest.raises(StorageSchemaError):
            store.open_existing(db_path=path)
        assert not path.exists()