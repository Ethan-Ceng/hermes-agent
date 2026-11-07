"""At-most-once send requests and retained terminal identities."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

cron_delivery_locks = scoped_table("cron_delivery_locks", key=())
cron_deliveries = scoped_table("cron_deliveries", Column("execution_id", LargeBinary, nullable=False),
    Column("job_json", LargeBinary, nullable=False), Column("content", LargeBinary, nullable=False),
    Column("for_failure", BigInteger, nullable=False, server_default="0"), Column("status", Text, nullable=False),
    Column("owner_process_id", LargeBinary), Column("owner_pid", BigInteger), Column("owner_started_at", BigInteger),
    Column("created_at", Text, nullable=False), Column("finished_at", Text), Column("error", LargeBinary),
    Column("created_order", BigInteger, nullable=False), Column("finished_order", BigInteger), key=("execution_id",),
    constraints=(CheckConstraint("status IN ('pending','delivering','delivered','failed','unknown','suppressed')", name="status"),))
cron_delivery_tombstones = scoped_table("cron_delivery_tombstones", Column("execution_id", LargeBinary, nullable=False),
    Column("terminal_status", Text, nullable=False), Column("finished_at", Text), key=("execution_id",),
    constraints=(CheckConstraint("terminal_status IN ('delivered','failed','unknown','suppressed')", name="status"),))
Index("ix_cron_delivery_store_pending", cron_deliveries.c.store_id, cron_deliveries.c.status, cron_deliveries.c.created_order)
