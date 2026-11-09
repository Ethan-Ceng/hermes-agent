"""Keep exact unexpired grants until their remote revocation is confirmed."""

from alembic import op

revision = '0030_room_revoke_debts'
down_revision = '0029_transcript_cursor'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes['schema'])
    conn.exec_driver_sql(f'CREATE TABLE {schema}.hosted_room_owed_revokes ('
        'store_id TEXT NOT NULL,room_id BYTEA NOT NULL,member_id BYTEA NOT NULL,grant_digest TEXT NOT NULL,'
        'target_url BYTEA NOT NULL,"grant" BYTEA NOT NULL,expires_at DOUBLE PRECISION NOT NULL,'
        'next_attempt_at DOUBLE PRECISION NOT NULL,created_at DOUBLE PRECISION NOT NULL,'
        'attempts BIGINT NOT NULL DEFAULT 0,held BIGINT NOT NULL DEFAULT 0,'
        'PRIMARY KEY(store_id,room_id,member_id,grant_digest),'
        'CONSTRAINT ck_hosted_room_owed_revokes_owed_revoke_finite_expiry CHECK '
        "(expires_at > '-Infinity'::double precision AND expires_at < 'Infinity'::double precision))")


def downgrade():
    raise RuntimeError('Fresh PostgreSQL datasets do not support back-migration')
