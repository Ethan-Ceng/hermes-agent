"""Frozen Cron attempts/incident schema, independent of the SQLite ledger."""

from alembic import op

revision = "0007_cron_executions"
down_revision = "0006_projects"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.cron_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.cron_executions (
        store_id TEXT NOT NULL, id BYTEA NOT NULL, job_id BYTEA NOT NULL, source BYTEA NOT NULL,
        process_id BYTEA NOT NULL, pid BIGINT NOT NULL, process_started_at BIGINT, status TEXT NOT NULL,
        handoff_pending BIGINT NOT NULL DEFAULT 0, handoff_started_at DOUBLE PRECISION,
        claimed_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, progress_at TEXT, scheduled_instant TEXT,
        error BYTEA, delivery_outcome BYTEA, claimed_order BIGINT NOT NULL, finished_order BIGINT,
        CONSTRAINT pk_cron_executions PRIMARY KEY (store_id,id),
        CONSTRAINT ck_cron_executions_status CHECK (status IN ('claimed','running','completed','failed','unknown','cancelled','missed')))""")
    conn.exec_driver_sql(f"""CREATE TABLE {schema}.cron_incidents (
        store_id TEXT NOT NULL, id BYTEA NOT NULL, job_id BYTEA NOT NULL, error_sig TEXT NOT NULL,
        state TEXT NOT NULL, failure_type BYTEA NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        acked_at TEXT, alerted_at TEXT, closed_at TEXT, error BYTEA NOT NULL, output_file BYTEA,
        last_seen_order BIGINT NOT NULL, CONSTRAINT pk_cron_incidents PRIMARY KEY (store_id,id))""")
    for name, table, columns in (
        ("ix_cron_execution_store_job", "cron_executions", "store_id,job_id,claimed_order"),
        ("ix_cron_execution_store_status", "cron_executions", "store_id,status,claimed_order"),
        ("ix_cron_execution_store_occurrence", "cron_executions", "store_id,job_id,scheduled_instant"),
        ("ix_cron_incident_store_job", "cron_incidents", "store_id,job_id"),
    ):
        conn.exec_driver_sql(f"CREATE INDEX {name} ON {schema}.{table} ({columns})")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
