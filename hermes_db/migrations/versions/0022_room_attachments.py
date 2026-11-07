"""Frozen private-content identity, attachment metadata and replayable file cleanup."""

from alembic import op

revision = "0022_room_attachments"
down_revision = "0021_room_policy"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_attachment_roots (store_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_attachment_blobs (store_id TEXT NOT NULL, blob_id TEXT NOT NULL, "
        "sha256 TEXT NOT NULL, size BIGINT NOT NULL CHECK(size>0), ref_count BIGINT NOT NULL CHECK(ref_count>0), "
        "created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,blob_id), UNIQUE(store_id,sha256))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_attachments (store_id TEXT NOT NULL, attachment_id TEXT NOT NULL, "
        "upload_id TEXT NOT NULL, room_id TEXT NOT NULL, event_id TEXT, kind TEXT NOT NULL, name BYTEA NOT NULL, catalog_name BYTEA NOT NULL, "
        "size BIGINT NOT NULL CHECK(size>0), mime TEXT NOT NULL, sha256 TEXT NOT NULL, blob_id TEXT NOT NULL, recipient_member_ids_json BYTEA NOT NULL, "
        "viewer_access BIGINT NOT NULL CHECK(viewer_access IN (0,1)), state TEXT NOT NULL CHECK(state IN ('uploaded','committed','disbanded')), "
        "created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, expires_at DOUBLE PRECISION, "
        "PRIMARY KEY(store_id,attachment_id), UNIQUE(store_id,room_id,upload_id), "
        f"FOREIGN KEY(store_id,blob_id) REFERENCES {schema}.hosted_room_attachment_blobs(store_id,blob_id) ON DELETE RESTRICT)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_attachments_room_state ON {schema}.hosted_room_attachments (store_id,room_id,state,created_at)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_attachments_expiry ON {schema}.hosted_room_attachments (store_id,expires_at)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_attachments_event ON {schema}.hosted_room_attachments (store_id,room_id,event_id)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_attachment_cleanup (store_id TEXT NOT NULL, blob_id TEXT NOT NULL, "
        "namespace TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,blob_id))")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
