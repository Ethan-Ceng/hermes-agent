"""Frozen pointer to a private, replayable Board import stage."""

from alembic import op

revision = "0018_kanban_imports"
down_revision = "0017_kanban_file_jobs"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"ALTER TABLE {schema}.kanban_file_jobs ADD COLUMN stage_root BYTEA")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
