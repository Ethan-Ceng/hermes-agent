"""Frozen persistent Cron delivery queue and terminal tombstones."""

from alembic import op

revision = "0008_cron_delivery"
down_revision = "0007_cron_executions"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.cron_delivery_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.cron_deliveries (
        store_id TEXT NOT NULL, execution_id BYTEA NOT NULL, job_json BYTEA NOT NULL, content BYTEA NOT NULL,
        for_failure BIGINT NOT NULL DEFAULT 0, status TEXT NOT NULL, owner_process_id BYTEA,
        owner_pid BIGINT, owner_started_at BIGINT, created_at TEXT NOT NULL, finished_at TEXT, error BYTEA,
        created_order BIGINT NOT NULL, finished_order BIGINT,
        CONSTRAINT pk_cron_deliveries PRIMARY KEY (store_id,execution_id),
        CONSTRAINT ck_cron_deliveries_status CHECK (status IN ('pending','delivering','delivered','failed','unknown','suppressed')))""")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.cron_delivery_tombstones (
        store_id TEXT NOT NULL, execution_id BYTEA NOT NULL, terminal_status TEXT NOT NULL, finished_at TEXT,
        CONSTRAINT pk_cron_delivery_tombstones PRIMARY KEY (store_id,execution_id),
        CONSTRAINT ck_cron_delivery_tombstones_status CHECK (terminal_status IN ('delivered','failed','unknown','suppressed')))""")
    conn.exec_driver_sql(f"CREATE INDEX ix_cron_delivery_store_pending ON {schema}.cron_deliveries (store_id,status,created_order)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
