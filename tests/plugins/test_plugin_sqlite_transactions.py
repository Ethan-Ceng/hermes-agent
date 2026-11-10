"""Published legacy SQLite helpers preserve plugin transaction and WAL safety behavior."""

import sqlite3

import pytest

from plugins.plugin_storage import configure_plugin_sqlite, plugin_sqlite_transaction


def test_plugin_transaction_commits_rolls_back_and_leaves_connection_open(tmp_path):
    connection = sqlite3.connect(tmp_path / 'plugin.db')
    try:
        connection.execute('CREATE TABLE records(value TEXT)')
        with plugin_sqlite_transaction(connection):
            connection.execute('INSERT INTO records VALUES (?)', ('committed',))
        with pytest.raises(ValueError, match='original failure'), plugin_sqlite_transaction(connection):
            connection.execute('INSERT INTO records VALUES (?)', ('rolled back',))
            raise ValueError('original failure')
        assert connection.execute('SELECT value FROM records').fetchall() == [('committed',)]
    finally:
        connection.close()


def test_plugin_wal_configuration_keeps_business_schema_untouched(tmp_path):
    connection = sqlite3.connect(tmp_path / 'plugin.db')
    try:
        connection.execute('CREATE TABLE records(value TEXT)')
        statements = []
        connection.set_trace_callback(statements.append)
        assert configure_plugin_sqlite(connection, db_label='plugin-test') in ('wal', 'delete')
        assert not any(sql.lstrip().upper().startswith(('CREATE', 'ALTER', 'DROP')) for sql in statements)
        with plugin_sqlite_transaction(connection):
            connection.execute('INSERT INTO records VALUES (?)', ('retained',))
        assert connection.execute('SELECT value FROM records').fetchone() == ('retained',)
    finally:
        connection.close()
