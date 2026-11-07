"""Driver lease and exact task attempt state in the owning room's scope."""

from sqlalchemy import BigInteger, CheckConstraint, Column, Float, LargeBinary, Text, UniqueConstraint
from hermes_db.tables.metadata import scoped_fk, scoped_table

leases = scoped_table("hosted_room_driver_leases", *[Column(name, Text, nullable=False) for name in (
    "room_id", "gateway_id", "process_generation")], Column("authority_epoch", BigInteger, nullable=False),
    Column("lease_generation", BigInteger, nullable=False), Column("expires_at", Float, nullable=False),
    Column("acquired_at", Float, nullable=False), Column("updated_at", Float, nullable=False), Column("released_at", Float),
    key=("room_id",), constraints=(scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),
        CheckConstraint("authority_epoch >= 1 AND lease_generation >= 1", name="driver_lease_counters")))
tasks = scoped_table("hosted_room_driver_tasks", *[Column(name, Text, nullable=False) for name in (
    "room_id", "task_id", "thread_id", "turn_id", "payload_digest", "status")],
    Column("source_event_seq", BigInteger, nullable=False), Column("payload_json", LargeBinary, nullable=False),
    Column("execution_generation", BigInteger, nullable=False, server_default="0"),
    Column("cancel_generation", BigInteger, nullable=False, server_default="0"),
    *[Column(name, Text) for name in ("run_gateway_id", "run_process_generation", "cancel_id", "settlement_id", "settlement_status")],
    Column("run_lease_generation", BigInteger), Column("result_json", LargeBinary),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False),
    *[Column(name, Float) for name in ("started_at", "terminal_at", "indeterminate_at")], key=("room_id", "task_id"),
    constraints=(scoped_fk(("room_id",), "hosted_rooms", ("room_id",), ondelete="CASCADE"),
        UniqueConstraint("store_id", "room_id", "thread_id", "turn_id"),
        CheckConstraint("source_event_seq >= 1 AND execution_generation >= 0 AND cancel_generation >= 0", name="driver_task_counters"),
        CheckConstraint("status IN ('queued','running','settled','failed','cancelled','indeterminate','deferred','stopping')", name="driver_task_status")))
