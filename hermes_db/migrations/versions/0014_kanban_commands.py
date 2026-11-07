"""Frozen Board-scoped mutation receipts."""

from alembic import op

revision = "0014_kanban_commands"
down_revision = "0013_kanban_dispatch"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_command_receipts (store_id TEXT NOT NULL, board_id TEXT NOT NULL, "
        "command_id TEXT NOT NULL, request_digest TEXT NOT NULL, result BYTEA NOT NULL, created_at BIGINT NOT NULL, "
        f"PRIMARY KEY (store_id,board_id,command_id), FOREIGN KEY (store_id,board_id) REFERENCES {schema}.kanban_boards(store_id,board_id) ON DELETE CASCADE)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
