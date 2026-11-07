"""Frozen room event, retired identity and replica storage."""

from alembic import op

revision = "0019_room_events"
down_revision = "0018_kanban_imports"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_store_locks (store_id TEXT PRIMARY KEY)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_rooms (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "name BYTEA NOT NULL, members_json BYTEA NOT NULL, authority_gateway_id TEXT NOT NULL, authority_epoch BIGINT NOT NULL, "
        "next_seq BIGINT NOT NULL, event_bytes BIGINT NOT NULL, revision BIGINT NOT NULL, created_at DOUBLE PRECISION NOT NULL, "
        "updated_at DOUBLE PRECISION NOT NULL, disbanded_at DOUBLE PRECISION, PRIMARY KEY(store_id,room_id), "
        "CHECK(authority_epoch >= 1 AND next_seq >= 1 AND revision >= 1))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_events (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "seq BIGINT NOT NULL CHECK(seq >= 1), event_id BYTEA NOT NULL, kind BYTEA NOT NULL, actor_json BYTEA NOT NULL, "
        "authority_epoch BIGINT CHECK(authority_epoch IS NULL OR authority_epoch >= 1), payload_json BYTEA NOT NULL, "
        "created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id,seq), UNIQUE(store_id,room_id,event_id), "
        f"FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_retired_ids (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "retired_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_replicas (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "name BYTEA NOT NULL, members_json BYTEA NOT NULL, authority_gateway_id TEXT NOT NULL, authority_epoch BIGINT NOT NULL, "
        "last_seq BIGINT NOT NULL, latest_seq BIGINT NOT NULL, event_bytes BIGINT NOT NULL, created_at DOUBLE PRECISION NOT NULL, "
        "updated_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_replica_events (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "seq BIGINT NOT NULL, event_id BYTEA NOT NULL, kind BYTEA NOT NULL, actor_json BYTEA NOT NULL, authority_epoch BIGINT, "
        "payload_json BYTEA NOT NULL, created_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id,seq), "
        f"FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_room_replicas(store_id,room_id) ON DELETE CASCADE)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_links (store_id TEXT NOT NULL, room_id BYTEA NOT NULL, "
        "member_id BYTEA NOT NULL, target_url BYTEA NOT NULL, target_profile BYTEA NOT NULL, \"grant\" BYTEA NOT NULL, "
        "catalog_json BYTEA NOT NULL, cancellation_scope_id BYTEA NOT NULL, trace_id BYTEA NOT NULL, "
        "transport_security BYTEA NOT NULL, status BYTEA NOT NULL, updated_at DOUBLE PRECISION NOT NULL, "
        "PRIMARY KEY(store_id,room_id,member_id))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_revoked_grants (store_id TEXT NOT NULL, scope_key TEXT NOT NULL, "
        "expires_at DOUBLE PRECISION NOT NULL, revoked_before DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,scope_key))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_peer_reservations (store_id TEXT NOT NULL, room_id BYTEA NOT NULL, "
        "member_id BYTEA NOT NULL, target_profile BYTEA NOT NULL, authority_gateway_id BYTEA NOT NULL, "
        "authority_epoch BIGINT NOT NULL CHECK(authority_epoch >= 1), expires_at DOUBLE PRECISION NOT NULL, revoked_at DOUBLE PRECISION, "
        "created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id,member_id,target_profile))")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_remote_runs (store_id TEXT NOT NULL, room_id BYTEA NOT NULL, "
        "home_install_id BYTEA NOT NULL, authority_gateway_id BYTEA NOT NULL, authority_epoch BIGINT NOT NULL CHECK(authority_epoch >= 1), "
        "member_id BYTEA NOT NULL, target_install_id BYTEA NOT NULL, target_profile BYTEA NOT NULL, task_id BYTEA NOT NULL, "
        "execution_generation BIGINT NOT NULL CHECK(execution_generation >= 1), run_id BYTEA NOT NULL, session_id BYTEA NOT NULL, "
        "created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, "
        "PRIMARY KEY(store_id,room_id,home_install_id,authority_gateway_id,authority_epoch,member_id,target_install_id,target_profile,task_id,execution_generation))")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
