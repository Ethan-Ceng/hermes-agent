"""Explicit Native queue schema lifecycle;ordinary provider startup never creates tables."""
from pathlib import Path
from plugins.plugin_storage import initialize_plugin_database, selected_storage_backend, plugin_profile_scope


def initialize_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, session_id TEXT, messages_json TEXT, created_at TEXT, last_error TEXT)')


def schema_ready(conn):
    columns = {row[1] for row in conn.execute('PRAGMA table_info(pending)')}
    return {'id', 'user_id', 'session_id', 'messages_json', 'created_at', 'last_error'}.issubset(columns)


def initialize_queue_schema(*, profile_home, db_path=None):
    if selected_storage_backend(profile_home) != 'sqlite':
        return
    with plugin_profile_scope(profile_home):
        initialize_plugin_database(Path(db_path) if db_path is not None else Path(profile_home) / 'retaindb_queue.db', db_label='RetainDB queue',
            initialize=initialize_schema, profile_home=profile_home, busy_timeout_ms=30000, wal=False, check_same_thread=False)
