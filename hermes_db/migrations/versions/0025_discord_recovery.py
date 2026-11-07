"""Frozen Discord recovery ledgers; cursors use the portable plugin namespace."""

from alembic import op

revision = "0025_discord_recovery"
down_revision = "0024_plugins"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.discord_recovery_locks(store_id TEXT NOT NULL,plugin_id TEXT NOT NULL,PRIMARY KEY(store_id,plugin_id))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.discord_recovery_messages(store_id TEXT NOT NULL,plugin_id TEXT NOT NULL,message_id BYTEA NOT NULL,"
        "channel_id BYTEA,thread_id BYTEA,parent_channel_id BYTEA,author_id BYTEA,response_message_id BYTEA,last_error BYTEA,created_at TEXT,status TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,last_attempt_at TEXT,replied BIGINT NOT NULL DEFAULT 0,emoji_ack BIGINT NOT NULL DEFAULT 0,"
        "outage_response BIGINT NOT NULL DEFAULT 0,attempts BIGINT NOT NULL DEFAULT 0,PRIMARY KEY(store_id,plugin_id,message_id),"
        "CHECK(attempts>=0 AND replied IN(0,1) AND emoji_ack IN(0,1) AND outage_response IN(0,1)))")
    conn.exec_driver_sql(f"CREATE INDEX idx_discord_messages_retention ON {schema}.discord_recovery_messages(store_id,plugin_id,updated_at)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.discord_recovery_scans(store_id TEXT NOT NULL,plugin_id TEXT NOT NULL,scan_id TEXT NOT NULL,"
        "started_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,channels BYTEA NOT NULL,window_seconds DOUBLE PRECISION NOT NULL,"
        "limit_count BIGINT NOT NULL,scanned BIGINT NOT NULL DEFAULT 0,missed BIGINT NOT NULL DEFAULT 0,dispatched BIGINT NOT NULL DEFAULT 0,error BYTEA,"
        "PRIMARY KEY(store_id,plugin_id,scan_id))")
    conn.exec_driver_sql(f"CREATE INDEX idx_discord_scans_retention ON {schema}.discord_recovery_scans(store_id,plugin_id,started_at)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
