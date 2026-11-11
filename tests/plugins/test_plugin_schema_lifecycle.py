"""Plugin ordinary opens do no DDL and failed portable creation is atomic."""
import re
import sqlite3

import pytest


def test_portable_schema_failure_is_atomic_and_ordinary_operations_do_no_ddl(tmp_path, monkeypatch):
    from plugins.plugin_storage import initialize_plugin_store, plugin_store, StorageSchemaError

    home = tmp_path / 'profile'
    path = home / 'plugin-data' / 'atomic' / 'portable.db'
    original = sqlite3.connect

    def denied_index(*args, **kwargs):
        conn = original(*args, **kwargs)
        def authorizer(action, first, second, database, trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_INDEX and first == 'idx_plugin_records_expiry' else sqlite3.SQLITE_OK
        conn.set_authorizer(authorizer)
        return conn

    with monkeypatch.context() as fault:
        fault.setattr(sqlite3, 'connect', denied_index)
        with pytest.raises(sqlite3.DatabaseError, match='authorized'):
            initialize_plugin_store('atomic', profile_home=home)
    with original(path) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('plugin_namespaces','plugin_records')").fetchone()[0] == 0
    with pytest.raises(StorageSchemaError):
        plugin_store('atomic', profile_home=home).get('missing')
    initialize_plugin_store('atomic', profile_home=home)
    statements = []
    def traced(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', traced)
    store = plugin_store('atomic', profile_home=home)
    row = store.put('key\x00', {'text': '值🙂'}, expected_revision=0)
    assert store.get('key\x00') == row
    assert not [sql for sql in statements if re.match(r'\s*(CREATE|ALTER|DROP)\b', sql, re.IGNORECASE)]


def test_legacy_plugin_startup_checks_existing_schema_without_ddl(tmp_path, monkeypatch):
    from plugins.platforms.discord.recovery import DiscordRecoveryStore, initialize_recovery_schema
    from plugins.memory.retaindb.storage_schema import initialize_queue_schema
    from plugins.memory.retaindb import _WriteQueue

    initialize_recovery_schema(tmp_path)
    initialize_queue_schema(profile_home=tmp_path)
    statements = []
    original = sqlite3.connect
    def traced(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', traced)
    assert DiscordRecoveryStore(tmp_path).cursor('channel') is None
    queue = _WriteQueue(object(), tmp_path / 'retaindb_queue.db', profile_home=tmp_path)
    try:
        assert queue._get_conn().execute('SELECT count(*) FROM pending').fetchone()[0] == 0
    finally:
        queue.shutdown()
    assert statements
    assert not [sql for sql in statements if re.match(r'\s*(CREATE|ALTER|DROP)\b', sql, re.IGNORECASE)]