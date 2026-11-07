"""Frozen per-job notepad schema; quota operations lock the job scope."""

from alembic import op

revision = "0009_cron_notepad"
down_revision = "0008_cron_delivery"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.cron_notepad_locks (store_id TEXT NOT NULL, job_id BYTEA NOT NULL, "
                         "CONSTRAINT pk_cron_notepad_locks PRIMARY KEY (store_id,job_id))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.cron_notepad (store_id TEXT NOT NULL, job_id BYTEA NOT NULL, "
        "key BYTEA NOT NULL, value BYTEA NOT NULL, updated_at TEXT NOT NULL, CONSTRAINT pk_cron_notepad PRIMARY KEY (store_id,job_id,key))")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
