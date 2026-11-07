"""Discord-owned message and scan ledgers scoped by Profile and plugin."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

locks = scoped_table("discord_recovery_locks", Column("plugin_id", Text, nullable=False), key=("plugin_id",))
messages = scoped_table("discord_recovery_messages", Column("plugin_id", Text, nullable=False),
    *[Column(name, LargeBinary, nullable=name != "message_id") for name in (
        "message_id", "channel_id", "thread_id", "parent_channel_id", "author_id", "response_message_id", "last_error")],
    Column("created_at", Text), Column("status", Text, nullable=False), Column("updated_at", Text, nullable=False),
    Column("last_attempt_at", Text), *[Column(name, BigInteger, nullable=False, server_default="0") for name in ("replied", "emoji_ack", "outage_response", "attempts")],
    key=("plugin_id", "message_id"), constraints=(CheckConstraint("attempts>=0 AND replied IN (0,1) AND emoji_ack IN (0,1) AND outage_response IN (0,1)", name="discord_message_counters"),))
Index("idx_discord_messages_retention", messages.c.store_id, messages.c.plugin_id, messages.c.updated_at)
scans = scoped_table("discord_recovery_scans", Column("plugin_id", Text, nullable=False), Column("scan_id", Text, nullable=False),
    Column("started_at", Text, nullable=False), Column("completed_at", Text), Column("status", Text, nullable=False),
    Column("channels", LargeBinary, nullable=False), Column("window_seconds", Float, nullable=False), Column("limit_count", BigInteger, nullable=False),
    *[Column(name, BigInteger, nullable=False, server_default="0") for name in ("scanned", "missed", "dispatched")], Column("error", LargeBinary), key=("plugin_id", "scan_id"))
Index("idx_discord_scans_retention", scans.c.store_id, scans.c.plugin_id, scans.c.started_at)
