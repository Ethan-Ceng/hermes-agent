"""Current PG revision upgrades backfill metadata markers without parsing JSON in SQL."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_model_marker_revision_backfills_both_stores_and_preserves_raw_json(postgres_test_config, postgres_schema, postgres_engine):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from hermes_db.infra.backends.postgresql.schema import prepare_schema
    from hermes_db.schema import REQUIRED_EXTENSIONS, _PG_TRGM_ACTION, upgrade_schema
    import hermes_db.schema as module

    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    directory = Path(module.__file__).parent / 'migrations'
    config = Config(str(directory / 'alembic.ini'))
    config.set_main_option('script_location', str(directory).replace('%', '%%'))
    config.attributes['schema'] = settings.schema
    quoted = postgres_engine.dialect.identifier_preparer.quote(settings.schema)
    raw = json.dumps({'_delegate_from': 'owner\x00bytes', '_branched_from': False,
        'browser_model_lock': {'model_options': {'stop': ['\x00']}}})
    with postgres_engine.begin() as conn:
        prepare_schema(conn, settings, required_extensions=REQUIRED_EXTENSIONS,
                       missing_extension_action=_PG_TRGM_ACTION)
        config.attributes['connection'] = conn
        command.upgrade(config, '0003_archive_refs')
        for store in ('first', 'second'):
            conn.execute(text(f'INSERT INTO {quoted}.transcript_roots(store_id,root_id) VALUES (:store,\'same\')'), {'store': store})
            conn.execute(text(f'INSERT INTO {quoted}.sessions(store_id,id,lineage_root_id,source,started_at,model_config) '
                "VALUES (:store,'same','same','cli',1,:raw)"), {'store': store, 'raw': raw})
            conn.execute(text(f'INSERT INTO {quoted}.messages(store_id,id,session_id,role,timestamp,display_metadata) '
                "VALUES (:store,1,'same','user',1,:raw)"),
                {'store': store, 'raw': json.dumps({'title_preview': 'before\x00after', 'gateway_input_owner': 'owner'})})
    assert upgrade_schema(settings)['ready']
    assert upgrade_schema(settings)['ready']
    with postgres_engine.connect() as conn:
        rows = conn.execute(text(f'SELECT store_id,model_config,delegate_origin,has_delegate_marker,has_branch_marker '
            f'FROM {quoted}.sessions ORDER BY store_id')).all()
    assert [row[0] for row in rows] == ['first', 'second']
    assert all(row[1] == raw and bytes(row[2]) == b'owner\x00bytes' and row[3:] == (1, 1) for row in rows)
    with postgres_engine.connect() as conn:
        rows = conn.execute(text(f'SELECT display_metadata,display_query FROM {quoted}.messages ORDER BY store_id')).all()
    assert len(rows) == 2
    assert all(json.loads(row[0])['title_preview'] == 'before\x00after' and
        row[1]['"title_preview"'.encode('ascii').hex()] == '"before\\u0000after"' and
        row[1]['"gateway_input_owner"'.encode('ascii').hex()] == '"owner"' for row in rows)
