"""Frozen scoped Kanban subscriptions and delivery cursors."""

from alembic import op

revision = "0016_kanban_notify"
down_revision = "0015_kanban_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_notify_subs (store_id TEXT NOT NULL, board_id TEXT NOT NULL, "
        "task_id BYTEA NOT NULL, platform BYTEA NOT NULL, chat_id BYTEA NOT NULL, thread_id BYTEA NOT NULL, "
        "user_id BYTEA, user_id_alt BYTEA, chat_type BYTEA, notifier_profile BYTEA, delivery_mode BYTEA NOT NULL, "
        "delivery_metadata BYTEA, platform_key BYTEA NOT NULL, created_at BIGINT NOT NULL, "
        "last_event_id BIGINT NOT NULL DEFAULT 0, last_ping_event_id BIGINT NOT NULL DEFAULT 0, "
        "PRIMARY KEY (store_id,board_id,task_id,platform,chat_id,thread_id), "
        f"FOREIGN KEY (store_id,board_id) REFERENCES {schema}.kanban_boards(store_id,board_id) ON DELETE CASCADE)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
