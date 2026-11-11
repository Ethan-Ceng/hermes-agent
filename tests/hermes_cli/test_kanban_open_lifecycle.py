"""Explicit board initialization and ordinary existing-store connections."""

import re
import sqlite3

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_cli.kanban_sqlite_schema import DECLARED_COLUMNS
from hermes_db.errors import StorageSchemaError


def test_default_board_open_does_not_create_a_missing_store(tmp_path):
    path = tmp_path / "kanban.db"
    with pytest.raises(StorageSchemaError, match="hermes kanban init"):
        kbc.connect(path)
    assert not path.exists()


def test_explicit_board_schema_and_ordinary_reopen(tmp_path, monkeypatch):
    path = tmp_path / "kanban.db"
    kbc.init_db(path)
    with kbc.connect_closing(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert tables == set(DECLARED_COLUMNS)
        for table, columns in DECLARED_COLUMNS.items():
            assert {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')} == set(columns.split())
        task = kb.create_task(conn, title="kept")
    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    kbc._INITIALIZED_PATHS.clear()
    kbc.initialize_new_board(path)
    with kbc.connect_closing(path) as conn:
        assert kb.get_task(conn, task).title == "kept"
    assert trace
    assert not [sql for sql in trace if re.match(r"\s*(CREATE|ALTER|DROP|REINDEX)\b", sql, re.IGNORECASE)]


def test_ordinary_corrupt_open_keeps_backup_and_requires_explicit_repair(tmp_path, monkeypatch):
    from tests.hermes_cli.test_kanban_db_repair import _corrupt_index

    path = tmp_path / "kanban.db"
    kbc.init_db(path)
    with kbc.connect_closing(path) as conn:
        for number in range(12):
            kb.create_task(conn, title=f"retained {number}")
    _corrupt_index(path, "idx_tasks_status")
    kbc._INITIALIZED_PATHS.clear()
    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    with pytest.raises(kbc.KanbanDbCorruptError) as refused:
        kbc.connect(path)
    assert refused.value.backup_path.is_file()
    assert not [sql for sql in trace if re.match(r"\s*(CREATE|ALTER|DROP|REINDEX)\b", sql, re.IGNORECASE)]
    kbc.init_db(path)
    with kbc.connect_closing(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 12
