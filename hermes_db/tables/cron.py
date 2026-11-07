"""Cron attempts and incidents share one scoped domain."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Double, Index, LargeBinary, Text
from hermes_db.tables.metadata import scoped_table

cron_locks = scoped_table("cron_locks", key=())
cron_executions = scoped_table("cron_executions", Column("id", LargeBinary, nullable=False),
    *[Column(name, LargeBinary, nullable=False) for name in ("job_id", "source", "process_id")],
    Column("pid", BigInteger, nullable=False), Column("process_started_at", BigInteger),
    Column("status", Text, nullable=False), Column("handoff_pending", BigInteger, nullable=False, server_default="0"),
    Column("handoff_started_at", Double), Column("claimed_at", Text, nullable=False),
    *[Column(name, Text) for name in ("started_at", "finished_at", "progress_at", "scheduled_instant")],
    Column("error", LargeBinary), Column("delivery_outcome", LargeBinary),
    Column("claimed_order", BigInteger, nullable=False), Column("finished_order", BigInteger), key=("id",),
    constraints=(CheckConstraint("status IN ('claimed','running','completed','failed','unknown','cancelled','missed')", name="status"),))
cron_incidents = scoped_table("cron_incidents", Column("id", LargeBinary, nullable=False),
    Column("job_id", LargeBinary, nullable=False), Column("error_sig", Text, nullable=False),
    Column("state", Text, nullable=False), Column("failure_type", LargeBinary, nullable=False),
    *[Column(name, Text, nullable=False) for name in ("first_seen_at", "last_seen_at")],
    *[Column(name, Text) for name in ("acked_at", "alerted_at", "closed_at")],
    Column("error", LargeBinary, nullable=False), Column("output_file", LargeBinary),
    Column("last_seen_order", BigInteger, nullable=False), key=("id",))
Index("ix_cron_execution_store_job", cron_executions.c.store_id, cron_executions.c.job_id, cron_executions.c.claimed_order)
Index("ix_cron_execution_store_status", cron_executions.c.store_id, cron_executions.c.status, cron_executions.c.claimed_order)
Index("ix_cron_execution_store_occurrence", cron_executions.c.store_id, cron_executions.c.job_id, cron_executions.c.scheduled_instant)
Index("ix_cron_incident_store_job", cron_incidents.c.store_id, cron_incidents.c.job_id)
