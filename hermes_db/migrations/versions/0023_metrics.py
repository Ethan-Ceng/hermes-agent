"""Frozen scoped metrics aggregation, consent and send outbox."""

from alembic import op

revision = "0023_metrics"
down_revision = "0022_room_attachments"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_store_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_state (store_id TEXT NOT NULL, key BYTEA NOT NULL, value BYTEA NOT NULL, PRIMARY KEY(store_id,key))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_counters (store_id TEXT NOT NULL, period_start TEXT NOT NULL, metric_name TEXT NOT NULL, "
        "hermes_version BYTEA NOT NULL, os_family TEXT NOT NULL, architecture TEXT NOT NULL, install_method TEXT NOT NULL, dimensions_json BYTEA NOT NULL, "
        "value BIGINT NOT NULL, packaged_value BIGINT NOT NULL DEFAULT 0, CHECK(value >= packaged_value AND packaged_value >= 0), "
        "PRIMARY KEY(store_id,period_start,metric_name,hermes_version,os_family,architecture,install_method,dimensions_json))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_packages (store_id TEXT NOT NULL, package_id TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, "
        "created_at TEXT NOT NULL, payload_json BYTEA NOT NULL, exported_at TEXT, sent_at TEXT, send_state TEXT, next_attempt_at TEXT, claim_token TEXT, "
        "last_error BYTEA, sent_install_id BYTEA, send_attempts BIGINT NOT NULL DEFAULT 0, PRIMARY KEY(store_id,package_id))")
    conn.exec_driver_sql(f"CREATE INDEX idx_metric_packages_pending ON {schema}.metric_packages (store_id,send_state,next_attempt_at,created_at)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_consent_windows (store_id TEXT NOT NULL, window_id TEXT NOT NULL, opened_at TEXT NOT NULL, "
        "last_confirmed_at TEXT NOT NULL, closed_at TEXT, PRIMARY KEY(store_id,window_id))")
    conn.exec_driver_sql(f"CREATE UNIQUE INDEX idx_metric_consent_open ON {schema}.metric_consent_windows(store_id) WHERE closed_at IS NULL")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.metric_consent_marks (store_id TEXT NOT NULL, name TEXT NOT NULL CHECK(name IN ('obs','data')), "
        "stamp TEXT NOT NULL, PRIMARY KEY(store_id,name))")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
