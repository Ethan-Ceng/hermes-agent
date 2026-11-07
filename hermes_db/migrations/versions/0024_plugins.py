"""Frozen portable plugin namespaces, revisions, values and TTL."""

from alembic import op

revision = "0024_plugins"
down_revision = "0023_metrics"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.plugin_namespaces (store_id TEXT NOT NULL, plugin_id TEXT NOT NULL, namespace TEXT NOT NULL, "
        "revision BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(store_id,plugin_id,namespace))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.plugin_records (store_id TEXT NOT NULL, plugin_id TEXT NOT NULL, namespace TEXT NOT NULL, "
        "key BYTEA NOT NULL, value BYTEA NOT NULL, revision BIGINT NOT NULL, expires_at DOUBLE PRECISION, PRIMARY KEY(store_id,plugin_id,namespace,key), "
        f"FOREIGN KEY(store_id,plugin_id,namespace) REFERENCES {schema}.plugin_namespaces(store_id,plugin_id,namespace) ON DELETE RESTRICT)")
    conn.exec_driver_sql(f"CREATE INDEX idx_plugin_records_expiry ON {schema}.plugin_records(store_id,plugin_id,namespace,expires_at)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
