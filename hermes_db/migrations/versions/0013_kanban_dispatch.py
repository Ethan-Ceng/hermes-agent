"""Frozen store-scoped automatic dispatch lease."""

from alembic import op

revision = "0013_kanban_dispatch"
down_revision = "0012_kanban_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_dispatch_leases (store_id TEXT PRIMARY KEY, "
                         "token TEXT NOT NULL, lease_until BIGINT NOT NULL)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
