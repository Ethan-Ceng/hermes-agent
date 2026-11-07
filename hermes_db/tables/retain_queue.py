"""RetainDB durable pending/claims and compact terminal receipts."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, Identity, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

pending = scoped_table("retain_pending", Column("plugin_id", Text, nullable=False), Column("request_id", Text, nullable=False),
    Column("sequence", BigInteger, Identity(), nullable=False), Column("destination_id", Text, nullable=False),
    Column("fingerprint", LargeBinary, nullable=False), Column("status", Text, nullable=False, server_default="pending"),
    *[Column(name, LargeBinary) for name in ("user_id", "session_id", "messages_json", "last_error")],
    Column("created_at", Float, nullable=False), Column("attempts", BigInteger, nullable=False, server_default="0"),
    Column("claim_token", Text), Column("lease_until", Float), Column("next_attempt_at", Float, nullable=False, server_default="0"),
    Column("acknowledged_at", Float), key=("plugin_id", "request_id"), constraints=(
        CheckConstraint("status IN ('pending','claimed','acknowledged') AND attempts>=0", name="retain_queue_state"),
        CheckConstraint("status='acknowledged' OR messages_json IS NOT NULL", name="retain_queue_payload")))
Index("idx_retain_pending_ready", pending.c.store_id, pending.c.plugin_id, pending.c.destination_id, pending.c.status, pending.c.next_attempt_at, pending.c.sequence)
