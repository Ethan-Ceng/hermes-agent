"""Frozen scoped mautrix 0.21.1 CryptoStore and SyncStore protocol data."""

from alembic import op

revision = "0027_matrix_crypto"
down_revision = "0026_retain_queue"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    owner = "store_id TEXT NOT NULL,account_key BYTEA NOT NULL,owner_device BYTEA NOT NULL,"
    primary = "store_id,account_key,owner_device"
    conn.exec_driver_sql(f"CREATE TABLE {schema}.matrix_roots({owner}generation TEXT NOT NULL,device_id BYTEA,sync_token BYTEA,account_pickle BYTEA,identity_key BYTEA,shared BIGINT NOT NULL DEFAULT 0,PRIMARY KEY({primary}))")
    specs = {
        "matrix_olm_sessions": ("sender_key BYTEA NOT NULL,session_id BYTEA NOT NULL,pickle BYTEA NOT NULL,created_at BYTEA,last_encrypted BYTEA,last_decrypted BYTEA,decrypted_order DOUBLE PRECISION", "sender_key,session_id"),
        "matrix_inbound_sessions": ("room_id BYTEA NOT NULL,session_id BYTEA NOT NULL,sender_key BYTEA,signing_key BYTEA,pickle BYTEA,forwarding_json BYTEA,ratchet_json BYTEA,received_at BYTEA,withheld_reason BYTEA,max_age_json BYTEA,received_order DOUBLE PRECISION,max_age_ms DOUBLE PRECISION,max_messages BIGINT,is_scheduled BIGINT NOT NULL DEFAULT 0,withheld_code TEXT", "room_id,session_id"),
        "matrix_outbound_sessions": ("room_id BYTEA NOT NULL,session_id BYTEA NOT NULL,pickle BYTEA NOT NULL,shared BIGINT NOT NULL,max_age_ms DOUBLE PRECISION NOT NULL,max_age_json BYTEA NOT NULL,max_messages BIGINT NOT NULL,message_count BIGINT NOT NULL,created_at BYTEA NOT NULL,last_used BYTEA NOT NULL", "room_id"),
        "matrix_message_indices": ("sender_key BYTEA NOT NULL,session_id BYTEA NOT NULL,message_index BIGINT NOT NULL,event_id BYTEA NOT NULL,timestamp BIGINT NOT NULL", "sender_key,session_id,message_index"),
        "matrix_tracked_users": ("user_id BYTEA NOT NULL", "user_id"),
        "matrix_devices": ("user_id BYTEA NOT NULL,device_id BYTEA NOT NULL,identity_key BYTEA NOT NULL,signing_key BYTEA NOT NULL,trust BIGINT NOT NULL,deleted BIGINT NOT NULL,name BYTEA", "user_id,device_id"),
        "matrix_cross_signing": ("user_id BYTEA NOT NULL,usage TEXT NOT NULL,key BYTEA NOT NULL,first_key BYTEA NOT NULL", "user_id,usage"),
        "matrix_signatures": ("target_user BYTEA NOT NULL,target_key BYTEA NOT NULL,signer_user BYTEA NOT NULL,signer_key BYTEA NOT NULL,signature BYTEA NOT NULL", "target_user,target_key,signer_user,signer_key"),
    }
    for table, (columns, key) in specs.items():
        conn.exec_driver_sql(f"CREATE TABLE {schema}.{table}({owner}{columns},PRIMARY KEY({primary},{key}),FOREIGN KEY({primary}) REFERENCES {schema}.matrix_roots({primary}) ON DELETE RESTRICT)")
    conn.exec_driver_sql(f"CREATE INDEX idx_matrix_inbound_expiry ON {schema}.matrix_inbound_sessions({primary},received_order)")
    conn.exec_driver_sql(f"CREATE INDEX idx_matrix_olm_latest ON {schema}.matrix_olm_sessions({primary},sender_key,decrypted_order)")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
