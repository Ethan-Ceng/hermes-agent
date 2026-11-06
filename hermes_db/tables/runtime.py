"""Scoped epoch, input FIFO, worker identity, and durable terminal metadata."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Identity, Index, LargeBinary, Text, UniqueConstraint

from hermes_db.tables.metadata import scoped_fk, scoped_table

runtime_epoch = scoped_table("runtime_epoch", Column("singleton", BigInteger, nullable=False),
    Column("epoch", BigInteger, nullable=False), Column("instance_id", Text, nullable=False), key=("singleton",),
    constraints=(CheckConstraint("singleton = 1", name="singleton"), CheckConstraint("epoch > 0", name="positive_epoch")))

session_admissions = scoped_table(
    "session_admissions", Column("seq", BigInteger, Identity(), nullable=False),
    *[Column(name, Text, nullable=False) for name in ("admission_id", "request_id", "principal_id", "target_session_id",
                                                   "lineage_json", "payload_json", "payload_digest", "intent", "status")],
    Column("outcome", Text), Column("owner_epoch", BigInteger), Column("generation", BigInteger),
    key=("admission_id",), constraints=(
        UniqueConstraint("store_id", "seq"),
        UniqueConstraint("store_id", "principal_id", "target_session_id", "request_id", name="uq_admissions_store_request"),
        scoped_fk(("target_session_id",), "sessions", ("id",), ondelete="RESTRICT"),
        CheckConstraint("intent IN ('queue','steer','redirect')", name="intent"),
        CheckConstraint("status IN ('queued','started','unknown','terminal')", name="status"),
        CheckConstraint("status != 'started' OR (owner_epoch IS NOT NULL AND generation IS NOT NULL)", name="started_owner"),
    ),
)
Index("ix_admissions_store_fifo", session_admissions.c.store_id, session_admissions.c.target_session_id,
      session_admissions.c.status, session_admissions.c.seq)

worker_executions = scoped_table(
    "worker_executions", *[Column(name, Text, nullable=False) for name in (
        "execution_id", "session_id", "kind", "status", "adoption_digest")],
    Column("owner_epoch", BigInteger, nullable=False), Column("generation", BigInteger, nullable=False),
    Column("last_sequence", BigInteger, nullable=False, server_default="0"), key=("execution_id",), constraints=(
        scoped_fk(("session_id",), "sessions", ("id",), ondelete="RESTRICT"),
        CheckConstraint("kind IN ('cron','child','compute','kanban')", name="kind"),
        CheckConstraint("status IN ('registered','running','unknown','terminal')", name="status"),
        CheckConstraint("last_sequence >= 0", name="sequence"),
    ),
)
Index("ix_workers_store_session_status", worker_executions.c.store_id, worker_executions.c.session_id, worker_executions.c.status)
Index("ix_workers_store_execution_prefix", worker_executions.c.store_id, worker_executions.c.execution_id,
      postgresql_ops={"execution_id": "text_pattern_ops"})
worker_receipts = scoped_table(
    "worker_receipts", Column("execution_id", Text, nullable=False), Column("sequence", BigInteger, nullable=False),
    Column("payload_digest", Text, nullable=False), Column("result_json", Text, nullable=False),
    Column("read_snapshot", BigInteger, nullable=False, server_default="0"),
    Column("title_candidate", LargeBinary),
    Column("assignment_parent", Text), Column("assignment_session", Text),
    key=("execution_id", "sequence"), constraints=(
        scoped_fk(("execution_id",), "worker_executions", ("execution_id",), ondelete="RESTRICT"),
        CheckConstraint("sequence > 0", name="sequence"),
        CheckConstraint("read_snapshot IN (0,1)", name="read_snapshot"),
    ),
)
state_meta = scoped_table("state_meta", Column("key", Text, nullable=False), Column("value", Text), key=("key",))
