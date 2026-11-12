"""Exercise supported source-bundle installs from outside the development tree."""

import json
import os
from pathlib import Path
import subprocess

import pytest


_PROBE = r'''
import importlib.util
import json
from pathlib import Path
import sys

import hermes_db
from hermes_cli.db_sessions import acquire_db
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings

source, home = map(Path, sys.argv[1:3])
backend = sys.argv[3]
package = Path(hermes_db.__file__).resolve()
assert package.is_relative_to(source.resolve() / 'hermes_db'), package
if backend == 'sqlite':
    from hermes_cli.db_session_schema import initialize_new_profile_sessions
    initialize_new_profile_sessions(home)
    with acquire_db(DatabaseSettings(), DatabaseScope(home)) as handle:
        handle.sessions.create_session('installed', 'cli')
        handle.sessions.append_message('installed', 'user', 'installed history')
        assert handle.sessions.get_messages_as_conversation('installed')[0]['content'] == 'installed history'
    assert importlib.util.find_spec('psycopg') is None
    assert not any(name.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic'} for name in sys.modules)
    from hermes_db.errors import StorageDriverError
    from hermes_db.settings import PostgresSettings
    try:
        acquire_db(DatabaseSettings('postgresql', PostgresSettings('postgresql://unused/never', 'hermes')),
                   DatabaseScope(home, 'artifact'))
    except StorageDriverError:
        pass
    else:
        raise AssertionError('Missing PostgreSQL extra must fail explicitly')
else:
    import sqlite3
    def reject_sqlite(event, args):
        if event == 'sqlite3.connect':
            raise AssertionError('SQLite is forbidden in the installed PG resource probe')
    sys.addaudithook(reject_sqlite)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from hermes_db.infra.postgresql.engine import require_postgresql_driver
    from hermes_db.schema import REQUIRED_REVISION
    from hermes_db.infra.postgresql.transactions import Transactions
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore
    require_postgresql_driver()
    migrations = package.parent / 'migrations'
    config = Config(str(migrations / 'alembic.ini'))
    config.set_main_option('script_location', str(migrations).replace('%', '%%'))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == REQUIRED_REVISION
    assert scripts.get_revision(REQUIRED_REVISION).path
    assert (migrations / 'env.py').is_file()
    from hermes_db.tables import load_metadata
    from hermes_db.core.catalog import POSTGRES_DOMAINS, KNOWN_DOMAINS, required_tables
    metadata = load_metadata()
    assert set(POSTGRES_DOMAINS) == set(KNOWN_DOMAINS)
    present = {table.name for table in metadata.tables.values()}
    assert all(required_tables(spec) <= present for spec in POSTGRES_DOMAINS.values())
print(json.dumps({'backend': backend, 'package': str(package), 'resources': True}))
'''


@pytest.mark.parametrize('backend', ['sqlite', 'postgresql'])
def test_distribution_has_sessions_and_migration_resources(request, tmp_path, backend):
    executable = request.config.getoption(f'--hermes-{backend}-python')
    source = request.config.getoption('--hermes-distribution-source')
    if not executable or not source:
        pytest.skip('Explicit PM-built distribution interpreters and independent payload are required')
    assert Path(executable).is_file()
    assert Path(source).is_dir()
    home = tmp_path / 'home'
    home.mkdir()
    env = {**os.environ, 'HERMES_HOME': str(home), 'HERMES_RUNTIME_DIR': str(home / 'runtime')}
    result = subprocess.run([executable, '-I', '-c', _PROBE, source, str(home), backend],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['resources']


def test_installed_sqlite_bundle_runs_business_without_pg(request, tmp_path):
    from tests.hermes_db.distribution_support import business_process
    first = business_process(request, tmp_path, "sqlite", "write")
    restarted = business_process(request, tmp_path, "sqlite", "read")
    assert first["pid"] != restarted["pid"] and len(restarted["domains"]) == 9


@pytest.mark.platforms("linux")
def test_installed_sqlite_bundle_restores_actual_sdk_crypto(request, tmp_path):
    from tests.hermes_db.distribution_support import business_process
    first = business_process(request, tmp_path, "sqlite", "write", matrix=True)
    restarted = business_process(request, tmp_path, "sqlite", "read", matrix=True)
    assert first["pid"] != restarted["pid"] and len(restarted["domains"]) == 10
