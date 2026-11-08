"""Initialize and reopen real PG through an independently installed source bundle."""

import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

_PROBE = r'''
import json
import os
from pathlib import Path
import sys

phase = 'imports'
try:
    import sqlite3
    def reject_sqlite(event, args):
        if event == 'sqlite3.connect':
            raise AssertionError('SQLite forbidden in installed PostgreSQL initialization')
    sys.addaudithook(reject_sqlite)
    import hermes_db
    from hermes_yaml import safe_load
    from sqlalchemy import text
    from hermes_db.engine import get_engine
    from hermes_db.factory import acquire_db
    from hermes_db.schema import REQUIRED_REVISION, upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings, PostgresSettings

    source, home = map(Path, sys.argv[1:3])
    assert Path(hermes_db.__file__).resolve().is_relative_to(source.resolve() / 'hermes_db')
    private = safe_load(Path(sys.argv[3]).read_text(encoding='utf-8'))
    settings = PostgresSettings(private['dsn'], sys.argv[4], pool_size=1, max_overflow=0,
        connection_budget=1, pool_timeout_seconds=2)
    phase = 'ownership'
    with get_engine(settings).connect() as conn:
        assert conn.scalar(text('SELECT current_database()')) == sys.argv[5]
        marker = conn.scalar(text("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname=:schema"),
            {'schema': settings.schema})
        assert marker == 'hermes-pg-tests:' + settings.schema.removeprefix('hermes_test_')
    database = DatabaseSettings('postgresql', settings)
    scope = DatabaseScope(home, 'installed-store')
    nul = chr(0)
    if sys.argv[6] == 'write':
        phase = 'previous-pg-revision'
        from alembic import command
        from alembic.config import Config
        from hermes_db.schema import _prepare_schema
        from contextlib import closing
        from hermes_db.session_store import PostgresSessionStore
        from hermes_db.postgresql.transactions import Transactions
        migrations = Path(hermes_db.__file__).parent / 'migrations'
        config = Config(str(migrations / 'alembic.ini'))
        config.set_main_option('script_location', str(migrations).replace('%', '%%'))
        config.attributes['schema'] = settings.schema
        with get_engine(settings).begin() as conn:
            _prepare_schema(conn, settings)
            config.attributes['connection'] = conn
            command.upgrade(config, '0004_model_markers')
        # Seed through the real session API and its content envelope, not malformed raw bytes.
        previous_scope = DatabaseScope(home / 'previous-pg', 'previous-pg')
        with closing(PostgresSessionStore(Transactions(get_engine(settings), settings.schema), previous_scope)) as previous:
            previous.create_session('before', 'cli', system_prompt='previous' + nul + 'prompt')
            previous.append_message('before', 'user', 'previous' + nul + 'history')
        phase = 'forward-upgrade'
        first = upgrade_schema(settings)
        assert first['ready'] and upgrade_schema(settings) == first
        phase = 'write'
        with acquire_db(database, scope) as handle:
            store, runtime = handle.sessions, handle.runtime
            store.create_session('installed', 'cli', system_prompt='prompt' + nul + 'exact',
                model_config={'browser_model_lock': {'model_options': {'stop': [nul]}}})
            store.append_message('installed', 'user', 'body' + nul + 'exact',
                display_metadata={'title_preview': 'preview' + nul + 'exact'})
            assert store.display_message_count('installed') == 1
            assert store.session_ids_with_model_config_key('browser_model_lock') == ['installed']
            epoch = runtime.begin_epoch(instance_id='installed-owner')
            args = dict(epoch=epoch, session_id='installed', principal_id='human', request_id='request', payload={'text': 'retained'})
            admission_id = runtime.admit_input(**args)['admission_id']
    else:
        old_epoch, admission_id = int(sys.argv[7]), sys.argv[8]
        with acquire_db(database, scope) as handle:
            assert handle.runtime.current_epoch() == old_epoch
            epoch = handle.runtime.begin_epoch(instance_id='restarted-owner')
            assert epoch == old_epoch + 1
        args = dict(epoch=epoch, session_id='installed', principal_id='human', request_id='request', payload={'text': 'retained'})
    phase = 'reopen'
    with acquire_db(database, DatabaseScope(home / 'previous-pg', 'previous-pg')) as previous:
        phase = 'previous-session-read'
        assert previous.sessions.get_session('before')['system_prompt'] == 'previous' + nul + 'prompt'
        phase = 'previous-history-read'
        assert previous.sessions.get_messages_as_conversation('before')[0]['content'] == 'previous' + nul + 'history'
    with acquire_db(database, scope) as handle:
        assert handle.sessions.get_messages_as_conversation('installed')[0]['content'] == 'body' + nul + 'exact'
        assert handle.sessions.get_session('installed')['system_prompt'] == 'prompt' + nul + 'exact'
        assert handle.runtime.admit_input(**args)['admission_id'] == admission_id
    with acquire_db(database, DatabaseScope(home / 'other', 'other-store')) as handle:
        if sys.argv[6] == 'write':
            assert handle.sessions.get_session('installed') is None
            handle.sessions.create_session('installed', 'cli')
            handle.sessions.append_message('installed', 'user', 'other scope')
        else:
            assert handle.sessions.get_messages_as_conversation('installed')[0]['content'] == 'other scope'
    assert not (home / 'state.db').exists()
    print(json.dumps({'ok': True, 'revision': REQUIRED_REVISION, 'scope_isolated': True, 'reopened': True,
        'pid': os.getpid(), 'epoch': epoch, 'admission_id': admission_id}))
except Exception as error:
    import re
    detail = str(error)
    if re.search(r'(?i)dsn|password|postgres(?:ql)?(?:\+psycopg)?://', detail):
        detail = 'redacted storage detail'
    print(json.dumps({'ok': False, 'phase': phase, 'error_type': type(error).__name__, 'detail': detail[:300]}))
    sys.exit(1)
'''


def test_installed_bundle_initializes_and_reopens_real_postgresql(request, postgres_schema, postgres_test_config, tmp_path):
    executable = request.config.getoption('--hermes-postgresql-python')
    source = request.config.getoption('--hermes-distribution-source')
    if not executable or not source:
        pytest.skip('Explicit PM-built installed PostgreSQL interpreter and independent payload required')
    from hermes_db.schema import REQUIRED_REVISION

    # Resolving a venv's interpreter symlink selects the base Python and loses its installation.
    executable, source = str(Path(executable).absolute()), str(Path(source).resolve())
    private_config = str(Path(request.config.getoption('--postgres-test-config')).resolve())
    assert Path(executable).is_file() and Path(source).is_dir()
    home = tmp_path / 'installed-home'
    home.mkdir()
    env = {**os.environ, 'HERMES_HOME': str(home), 'HERMES_RUNTIME_DIR': str(home / 'runtime')}
    command = [executable, '-I', '-c', _PROBE, source, str(home),
        private_config, postgres_schema, postgres_test_config.database]
    written = subprocess.run([*command, 'write'], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=180, check=False)
    assert written.returncode == 0, written.stdout + written.stderr
    first = json.loads(written.stdout.splitlines()[-1])
    reopened = subprocess.run([*command, 'restart', str(first['epoch']), first['admission_id']],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180, check=False)
    assert reopened.returncode == 0, reopened.stdout + reopened.stderr
    report = json.loads(reopened.stdout.splitlines()[-1])
    assert first['pid'] != report['pid']
    assert report['epoch'] == first['epoch'] + 1
    assert report['ok'] and report['scope_isolated'] and report['reopened']
    assert report['revision'] == REQUIRED_REVISION and report['admission_id'] == first['admission_id']


@pytest.mark.platforms("linux")
def test_installed_bundle_runs_all_pg_domains_and_actual_sdk_after_restart(request, postgres_schema, postgres_test_config, tmp_path):
    from tests.hermes_db.distribution_support import business_process
    first = business_process(request, tmp_path, "postgresql", "write", schema=postgres_schema, database=postgres_test_config.database)
    restarted = business_process(request, tmp_path, "postgresql", "read", schema=postgres_schema, database=postgres_test_config.database)
    assert first["pid"] != restarted["pid"]
    assert len(restarted["domains"]) == 10 and restarted["profiles"] == 2
    assert first["sqlite_connections"] == restarted["sqlite_connections"] == 0
