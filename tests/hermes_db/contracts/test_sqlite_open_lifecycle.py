"""Ordinary acquisitions only read the schema of an existing SQLite store."""

import json
import os
import re
import sqlite3
import subprocess
import sys

import pytest

from hermes_cli.db_sessions import acquire_sessions
from hermes_db.errors import StorageSchemaError
from hermes_state import SessionDB
from hermes_state_registry import release


DDL = re.compile(r"^\s*(?:CREATE|ALTER|DROP|REINDEX)\b", re.IGNORECASE)


def test_ordinary_acquisition_refuses_absent_store(tmp_path):
    path = tmp_path / "new" / "state.db"
    with pytest.raises(StorageSchemaError, match="hermes db upgrade"):
        acquire_sessions(path)
    assert not path.parent.exists()


def test_ordinary_acquisition_reads_and_writes_without_ddl(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    with SessionDB(path) as db:
        db.create_session("seed", source="cli")
    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    db = acquire_sessions(path)
    try:
        assert db.get_session("seed") is not None
        db.append_message("seed", role="user", content="new write")
    finally:
        release(db)
    assert any("INSERT INTO messages" in sql for sql in trace)
    assert not [sql for sql in trace if DDL.search(sql)]

    code = r"""
import json, os, re, sqlite3, sys
from pathlib import Path
from hermes_state import SessionDB
trace = []
connect = sqlite3.connect
def traced(*args, **kwargs):
    conn = connect(*args, **kwargs)
    conn.set_trace_callback(trace.append)
    return conn
sqlite3.connect = traced
with SessionDB.open_existing(Path(sys.argv[1])) as db:
    assert db.get_messages('seed')[0]['content'] == 'new write'
    db.append_message('seed', role='assistant', content='new process')
assert not [sql for sql in trace if re.match(r'^\s*(CREATE|ALTER|DROP|REINDEX)\b', sql, re.IGNORECASE)]
print(json.dumps({'pid': os.getpid()}))
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(path)],
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["pid"] != os.getpid()
    with SessionDB.open_existing(path, read_only=True) as db:
        assert [row["content"] for row in db.get_messages("seed")] == ["new write", "new process"]


def test_ordinary_writer_does_not_recreate_a_file_lost_before_connect(tmp_path, monkeypatch):
    from hermes_db.infra.backends.sqlite.session_connections import SQLiteConnections

    path = tmp_path / "state.db"
    SessionDB(path).close()
    connect = SQLiteConnections.connect_existing_writer

    def remove_before_connect(resource):
        path.unlink()
        return connect(resource)

    monkeypatch.setattr(SQLiteConnections, "connect_existing_writer", remove_before_connect)
    with pytest.raises(sqlite3.OperationalError, match="unable to open"):
        SessionDB.open_existing(path)
    assert not path.exists()
