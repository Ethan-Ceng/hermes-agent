"""Repair reserved delegate roots and legacy safety-refusal tails explicitly."""

from alembic import op

revision = '0031_merge_data_repair'
down_revision = '0030_room_revoke_debts'
branch_labels = None
depends_on = None


def upgrade():
    from hermes_db.migrations.merge_data_repair import repair
    repair(op.get_bind(), op.get_context().config.attributes['schema'])


def downgrade():
    raise RuntimeError('Fresh PostgreSQL datasets do not support back-migration')
