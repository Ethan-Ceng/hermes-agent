"""Frozen Board file-operation intents; no file I/O belongs in the migration."""

from alembic import op

revision = "0017_kanban_file_jobs"
down_revision = "0016_kanban_notify"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_file_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_file_jobs (store_id TEXT NOT NULL, board_id TEXT NOT NULL, "
        "slug TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', owner_home BYTEA NOT NULL, data_root BYTEA NOT NULL, "
        "attachments_root BYTEA NOT NULL, workspaces_root BYTEA NOT NULL, logs_root BYTEA NOT NULL, "
        "created_at BIGINT NOT NULL, PRIMARY KEY (store_id,board_id))")
    conn.exec_driver_sql(f"ALTER TABLE {schema}.kanban_attachments ADD COLUMN path_key BYTEA")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
