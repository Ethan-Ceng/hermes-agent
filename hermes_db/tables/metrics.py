"""Profile-scoped metric aggregates, immutable packages and consent observations."""

from sqlalchemy import BigInteger, CheckConstraint, Column, LargeBinary, Text, Index
from hermes_db.tables.metadata import scoped_table

locks = scoped_table("metric_store_locks", key=())
state = scoped_table("metric_state", Column("key", LargeBinary, nullable=False), Column("value", LargeBinary, nullable=False), key=("key",))
RESOURCE = ("hermes_version", "os_family", "architecture", "install_method")
COUNTER_KEY = ("period_start", "metric_name", *RESOURCE, "dimensions_json")
counters = scoped_table("metric_counters", Column("period_start", Text, nullable=False), Column("metric_name", Text, nullable=False),
    Column("hermes_version", LargeBinary, nullable=False), *[Column(name, Text, nullable=False) for name in RESOURCE[1:]],
    Column("dimensions_json", LargeBinary, nullable=False), Column("value", BigInteger, nullable=False),
    Column("packaged_value", BigInteger, nullable=False, server_default="0"), key=COUNTER_KEY,
    constraints=(CheckConstraint("value >= packaged_value AND packaged_value >= 0", name="metric_counter_values"),))
packages = scoped_table("metric_packages", *[Column(name, Text, nullable=False) for name in ("package_id", "period_start", "period_end", "created_at")],
    Column("payload_json", LargeBinary, nullable=False), *[Column(name, Text) for name in (
        "exported_at", "sent_at", "send_state", "next_attempt_at", "claim_token")],
    Column("last_error", LargeBinary), Column("sent_install_id", LargeBinary),
    Column("send_attempts", BigInteger, nullable=False, server_default="0"), key=("package_id",))
Index("idx_metric_packages_pending", packages.c.store_id, packages.c.send_state, packages.c.next_attempt_at, packages.c.created_at)
windows = scoped_table("metric_consent_windows", Column("window_id", Text, nullable=False),
    Column("opened_at", Text, nullable=False), Column("last_confirmed_at", Text, nullable=False), Column("closed_at", Text), key=("window_id",))
Index("idx_metric_consent_open", windows.c.store_id, unique=True, postgresql_where=windows.c.closed_at.is_(None))
marks = scoped_table("metric_consent_marks", Column("name", Text, nullable=False), Column("stamp", Text, nullable=False), key=("name",),
    constraints=(CheckConstraint("name IN ('obs','data')", name="metric_consent_mark_name"),))
