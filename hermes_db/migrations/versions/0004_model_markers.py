"""Frozen JSON query projections; original model/display JSON is never rewritten."""

import json

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004_model_markers'
down_revision = '0003_archive_refs'
branch_labels = None
depends_on = None


def _backfill(connection, table):
    cursor = ('', '')
    query = text(f'SELECT store_id,id,model_config FROM {table} WHERE (store_id,id) > (:store,:id) ORDER BY store_id,id LIMIT 128')
    update = text(f'UPDATE {table} SET delegate_origin=:origin,has_delegate_marker=:delegate,has_branch_marker=:branch '
        'WHERE store_id=:store AND id=:id')
    while rows := connection.execute(query, {'store': cursor[0], 'id': cursor[1]}).mappings().all():
        changes = []
        for row in rows:
            raw = json.loads(row['model_config']) if row['model_config'] else None
            config = raw if isinstance(raw, dict) else {}
            origin = config.get('_delegate_from')
            changes.append({'store': row['store_id'], 'id': row['id'],
                'origin': origin.encode('utf-8') if isinstance(origin, str) else None,
                'delegate': int(origin is not None), 'branch': int(config.get('_branched_from') is not None)})
        connection.execute(update, changes)
        cursor = rows[-1]['store_id'], rows[-1]['id']


def _backfill_display(connection, table):
    cursor = ('', -1)
    query = text(f'SELECT store_id,id,display_metadata FROM {table} WHERE (store_id,id) > (:store,:id) ORDER BY store_id,id LIMIT 128')
    update = text(f'UPDATE {table} SET display_query=:value WHERE store_id=:store AND id=:id').bindparams(bindparam('value', type_=JSONB))
    while rows := connection.execute(query, {'store': cursor[0], 'id': cursor[1]}).mappings().all():
        changes = []
        for row in rows:
            metadata = json.loads(row['display_metadata']) if row['display_metadata'] else {}
            projection = {json.dumps(key, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii').hex():
                None if value is None else json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
                for key, value in metadata.items()}
            changes.append({'store': row['store_id'], 'id': row['id'], 'value': projection})
        connection.execute(update, changes)
        cursor = rows[-1]['store_id'], rows[-1]['id']


def upgrade():
    connection = op.get_bind()
    quote = connection.dialect.identifier_preparer.quote
    table = quote(op.get_context().config.attributes['schema']) + '.sessions'
    connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN delegate_origin BYTEA, '
        'ADD COLUMN has_delegate_marker BIGINT NOT NULL DEFAULT 0, ADD COLUMN has_branch_marker BIGINT NOT NULL DEFAULT 0')
    _backfill(connection, table)
    table = quote(op.get_context().config.attributes['schema']) + '.messages'
    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN display_query JSONB NOT NULL DEFAULT '{{}}'::jsonb")
    _backfill_display(connection, table)


def downgrade():
    raise RuntimeError('Session storage downgrade is unsupported; use an administrator-managed database backup')
