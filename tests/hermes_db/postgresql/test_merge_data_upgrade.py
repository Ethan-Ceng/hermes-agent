"""Forward upgrade repairs existing PG rows atomically and refuses live ownership."""

from dataclasses import replace
from pathlib import Path
import time
import pytest
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def old_store(postgres_test_config, postgres_schema, tmp_path):
    from alembic import command
    from alembic.config import Config
    from hermes_db.infra.postgresql.engine import get_engine
    from hermes_db.infra.postgresql.schema import prepare_schema
    from hermes_db.schema import REQUIRED_EXTENSIONS, _PG_TRGM_ACTION
    from hermes_db.infra.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA
    from hermes_db.scope import DatabaseScope
    from hermes_cli.db_sessions import create_session_store
    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    directory = Path(__file__).parents[3] / 'hermes_db' / 'migrations'
    config = Config(str(directory / 'alembic.ini'))
    config.set_main_option('script_location', str(directory).replace('%', '%%'))
    config.attributes['schema'] = settings.schema
    with get_engine(settings).begin() as conn:
        prepare_schema(conn, settings, required_extensions=REQUIRED_EXTENSIONS,
                       missing_extension_action=_PG_TRGM_ACTION)
        config.attributes['connection'] = conn
        command.upgrade(config, '0030_room_revoke_debts')
    store = create_session_store(Transactions(get_engine(settings), settings.schema,
        lock_timeout=settings.write_lock_timeout_seconds, statement_timeout=settings.statement_timeout_seconds, schema_token=SCHEMA),
        DatabaseScope(tmp_path, 'upgrade-owner'))
    try:
        yield store, settings
    finally:
        store.close()


def seed_refusal(store, session_id, *, source='cli'):
    store.create_session(session_id, source)
    store.append_message(session_id, 'user', 'accepted')
    store.append_message(session_id, 'assistant', 'answer')
    store.append_message(session_id, 'user', 'blocked', display_metadata={'reactions': {'keep': 1}})
    store.append_message(session_id, 'assistant', 'failure', display_kind='failed_turn',
        display_metadata={'error_surface': {'code': 'content_policy_blocked'}})


def test_forward_upgrade_repairs_delegate_roots_and_refusal_once(old_store):
    from hermes_db.schema import upgrade_schema
    from hermes_db.tables.conversations import sessions
    from hermes_db.domains.sessions.postgres.queries import sessions as repo
    from hermes_db.core.values import model_config
    store, settings = old_store
    store.create_session('parent', 'cli')
    store.end_session('parent', 'compression')
    store.create_session('child', 'subagent', parent_session_id='parent')
    store.end_session('child', 'compression')
    store.create_session('continuation', 'subagent', parent_session_id='child')
    # Recreate the old mistaken materialized root, rather than merely testing a new empty schema.
    with store._write() as conn:
        conn.execute(sessions.update().where(sessions.c.store_id == store.scope.store_id,
            sessions.c.id.in_(['child', 'continuation'])).values(lineage_root_id='parent'))
    seed_refusal(store, 'locked')
    seed_refusal(store, 'task', source='cron')
    assert upgrade_schema(settings)['full_system_ready']
    assert model_config(store.get_session('child')['model_config'])['_delegate_from'] == 'parent'
    assert '_delegate_from' not in model_config(store.get_session('continuation')['model_config'])
    with store._read() as conn:
        roots = dict(conn.execute(select(sessions.c.id, sessions.c.lineage_root_id).where(
            sessions.c.store_id == store.scope.store_id)).all())
    assert roots['parent'] == 'parent' and roots['child'] == roots['continuation'] == 'child'
    assert [row['content'] for row in store.get_messages('locked')] == ['accepted', 'answer']
    shown = store.get_messages('locked', include_compacted=True)
    assert shown[-1]['content'] == 'blocked' and shown[-1]['display_metadata']['reactions'] == {'keep': 1}
    assert len(store.get_messages('task')) == 4
    rewinds = store.get_session('locked')['rewind_count']
    assert upgrade_schema(settings)['full_system_ready']
    assert store.get_session('locked')['rewind_count'] == rewinds


def test_upgrade_refuses_live_lease_and_rolls_back_all_repairs(old_store):
    from hermes_db.schema import upgrade_schema, schema_status
    from hermes_db.tables.gateway import session_turn_leases
    from hermes_db.errors import StorageSchemaError
    store, settings = old_store
    seed_refusal(store, 'locked')
    with store._write() as conn:
        conn.execute(session_turn_leases.insert().values(store_id=store.scope.store_id, conversation_id='locked',
            holder='live-owner', acquired_at=time.time(), expires_at=time.time() + 1000))
    with pytest.raises(StorageSchemaError, match='stopped and drained'):
        upgrade_schema(settings)
    assert schema_status(settings)['revision'] == '0030_room_revoke_debts'
    assert len(store.get_messages('locked')) == 4
    with store._write() as conn:
        conn.execute(session_turn_leases.delete().where(session_turn_leases.c.store_id == store.scope.store_id))
    assert upgrade_schema(settings)['full_system_ready']
    assert len(store.get_messages('locked')) == 2


@pytest.mark.parametrize('order', ['oldest', 'latest'])
def test_legacy_pg_display_index_survives_upgrade_and_stable_pages(old_store, order):
    from gateway.session_stored_reads import read_transcript, _decode_cursor
    from hermes_db.schema import upgrade_schema
    from hermes_db.tables.conversations import messages
    store, settings = old_store
    store.create_session('legacy', 'cli')
    store.append_message('legacy', 'user', 'old prompt')
    store.append_message('legacy', 'assistant', 'old reply')
    # The nullable projection is a legal older PG row shape, independent of SQLite data.
    with store._write() as conn:
        conn.execute(messages.update().where(messages.c.store_id == store.scope.store_id,
            messages.c.session_id == 'legacy').values(display_identity=None, display_order=None))
    assert upgrade_schema(settings)['full_system_ready']
    binding = ('legacy', None, order)
    def page(cursor=None):
        return read_transcript(store, 'legacy', ['legacy'], binding, cursor, 2,
            profile_home=store.scope.profile_home, inline_images=False)
    first = page()
    assert [row['text'] for row in first['rows']] == ['old prompt', 'old reply']
    assert store.transcript_display_index_complete('legacy')
    if order == 'oldest':
        next_page = page(_decode_cursor(first['next_cursor'], binding))
        assert not next_page['reset'] and next_page['rows'] == []
    assert [row['text'] for row in page()['rows']] == ['old prompt', 'old reply']
