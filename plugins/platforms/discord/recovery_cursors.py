"""Discord cursor consumer of portable PG plugin records; SQLite history stays native."""

from hermes_cli.db_setup import storage_backend

NAMESPACE = "recovery-cursors"
RETENTION_SECONDS = 30 * 24 * 3600


def _store(adapter):
    from plugins.plugin_storage import plugin_store
    return plugin_store("discord", namespace=NAMESPACE, profile_home=adapter._discord_recovery_store._hermes_home)


def cursor(adapter, channel_id):
    if not channel_id:
        return None
    home = adapter._discord_recovery_store._hermes_home
    if storage_backend(home) == "postgresql":
        row = _store(adapter).get(channel_id)
        return None if row is None else row.value
    def read(conn):
        row = conn.execute("SELECT last_message_id FROM discord_recovery_cursors WHERE channel_id=?", (channel_id,)).fetchone()
        return str(row[0]) if row else None
    return adapter._with_discord_recovery_db(read)


def advance(adapter, channel_id, message_id):
    if not channel_id or not message_id:
        return
    home = adapter._discord_recovery_store._hermes_home
    if storage_backend(home) == "postgresql":
        _store(adapter).put(channel_id, message_id, ttl_seconds=RETENTION_SECONDS)
        return
    stamp = adapter._utc_now_iso()
    def write(conn):
        conn.execute("INSERT INTO discord_recovery_cursors(channel_id,last_message_id,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET last_message_id=excluded.last_message_id,updated_at=excluded.updated_at", (channel_id, message_id, stamp))
    adapter._with_discord_recovery_db(write)
