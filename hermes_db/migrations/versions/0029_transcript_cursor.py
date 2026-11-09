"""Keep append fencing distinct from transcript cursor edit invalidation."""
from alembic import op

revision = "0029_transcript_cursor"
down_revision = "0028_kanban_effects"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"ALTER TABLE {schema}.sessions ADD COLUMN transcript_edit_revision BIGINT NOT NULL DEFAULT 0")
    conn.exec_driver_sql(f"UPDATE {schema}.sessions SET transcript_edit_revision=transcript_revision")


def downgrade():
    raise RuntimeError("Fresh PostgreSQL datasets do not support back-migration")
