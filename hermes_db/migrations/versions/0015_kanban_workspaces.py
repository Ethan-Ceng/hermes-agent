"""Frozen canonical workspace references and cross-Board cleanup fences."""

from alembic import op

revision = "0015_kanban_workspaces"
down_revision = "0014_kanban_commands"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_workspace_paths (store_id TEXT NOT NULL, path_key BYTEA NOT NULL, "
        "cleanup_token TEXT, PRIMARY KEY (store_id,path_key))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_workspace_refs (store_id TEXT NOT NULL, board_id TEXT NOT NULL, "
        "task_id BYTEA NOT NULL, path_key BYTEA NOT NULL, PRIMARY KEY (store_id,board_id,task_id), "
        f"FOREIGN KEY (store_id,board_id,task_id) REFERENCES {schema}.kanban_tasks(store_id,board_id,id) ON DELETE CASCADE, "
        f"FOREIGN KEY (store_id,path_key) REFERENCES {schema}.kanban_workspace_paths(store_id,path_key))")
    conn.exec_driver_sql(f"CREATE INDEX ix_kanban_workspace_refs_path ON {schema}.kanban_workspace_refs (store_id,path_key)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
