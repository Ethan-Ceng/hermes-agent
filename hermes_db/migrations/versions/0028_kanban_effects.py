"""Durable post-commit effects for Kanban transitions and receipt replay."""

from alembic import op

revision = "0028_kanban_effects"
down_revision = "0027_matrix_crypto"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"ALTER TABLE {schema}.kanban_workspace_paths ADD COLUMN cleanup_payload BYTEA")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.kanban_postcommit_effects (store_id TEXT NOT NULL,board_id TEXT NOT NULL,"
        "effect_id TEXT NOT NULL,owner_home BYTEA NOT NULL,payload BYTEA NOT NULL,phase BIGINT NOT NULL DEFAULT 0,"
        "claim TEXT,expires_at DOUBLE PRECISION,PRIMARY KEY(store_id,board_id,effect_id),"
        f"FOREIGN KEY(store_id,board_id) REFERENCES {schema}.kanban_boards(store_id,board_id) ON DELETE CASCADE)")


def downgrade():
    raise RuntimeError("Fresh PostgreSQL datasets do not support back-migration")
