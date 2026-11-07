"""Frozen policy projections, opaque publication keys and durable router claims."""

import json
from alembic import op
from sqlalchemy import text

revision = "0021_room_policy"
down_revision = "0020_room_runs"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"ALTER TABLE {schema}.hosted_room_policy_publications ALTER COLUMN task_id TYPE BYTEA USING convert_to(task_id,'UTF8')")
    conn.exec_driver_sql(f"ALTER TABLE {schema}.hosted_room_events ADD COLUMN policy_thread_key BYTEA, ADD COLUMN policy_discussion_key BYTEA")
    _backfill(conn, schema)
    conn.exec_driver_sql(f"CREATE INDEX idx_room_event_policy_thread ON {schema}.hosted_room_events (store_id,room_id,kind,policy_thread_key,seq)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_event_policy_discussion ON {schema}.hosted_room_events (store_id,room_id,policy_discussion_key,seq)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_policy_capacity (store_id TEXT NOT NULL, singleton BIGINT NOT NULL CHECK(singleton=1), "
        "max_active_events BIGINT NOT NULL CHECK(max_active_events>=1), PRIMARY KEY(store_id,singleton))")
    definitions = {
        "cursors": ("through_seq BIGINT NOT NULL, stopped_through_seq BIGINT NOT NULL, updated_at DOUBLE PRECISION NOT NULL", ""),
        "threads": ("thread_id BYTEA NOT NULL, discussion_event_id BYTEA NOT NULL, latest_user_seq BIGINT NOT NULL, completed BIGINT NOT NULL", ",thread_id"),
        "events": ("thread_id BYTEA NOT NULL, discussion_event_id BYTEA NOT NULL, seq BIGINT NOT NULL, event_json BYTEA NOT NULL, kind TEXT NOT NULL", ",seq"),
        "watermarks": ("thread_id BYTEA NOT NULL, member_id BYTEA NOT NULL, seen_through_seq BIGINT NOT NULL", ",thread_id,member_id"),
        "transcript": ("thread_id BYTEA NOT NULL, seq BIGINT NOT NULL, kind TEXT NOT NULL, settled_seq BIGINT", ",thread_id,seq"),
        "transcript_state": ("schema_version BIGINT NOT NULL", ""),
    }
    for suffix, (columns, key) in definitions.items():
        conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_policy_{suffix} (store_id TEXT NOT NULL, room_id TEXT NOT NULL, {columns}, "
            f"PRIMARY KEY(store_id,room_id{key}), FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_policy_pending ON {schema}.hosted_room_policy_threads (store_id,room_id,completed,latest_user_seq,thread_id)")
    conn.exec_driver_sql(f"CREATE INDEX idx_room_policy_active ON {schema}.hosted_room_policy_events (store_id,room_id,discussion_event_id,kind,seq)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_router_claims (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "discussion_event_id BYTEA NOT NULL, owner TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(store_id,room_id,discussion_event_id))")


def _backfill(conn, schema):
    rows = conn.execute(text(f"SELECT store_id,room_id,seq,payload_json FROM {schema}.hosted_room_events")).mappings()
    for row in rows:
        payload = json.loads(bytes(row["payload_json"]))
        fields = {key: payload.get(field).encode("utf-8") if isinstance(payload.get(field), str) else None
                  for key, field in (("thread", "thread_id"), ("discussion", "discussion_event_id"))}
        conn.execute(text(f"UPDATE {schema}.hosted_room_events SET policy_thread_key=:thread, policy_discussion_key=:discussion "
            "WHERE store_id=:store AND room_id=:room AND seq=:seq"),
            dict(fields, store=row["store_id"], room=row["room_id"], seq=row["seq"]))


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
