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
from hermes_db.factory import acquire_db
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings

source, home = map(Path, sys.argv[1:3])
package = Path(hermes_db.__file__).resolve()
assert package.is_relative_to(source.resolve() / 'hermes_db'), package
with acquire_db(DatabaseSettings(), DatabaseScope(home)) as handle:
    handle.sessions.create_session('installed', 'cli')
    handle.sessions.append_message('installed', 'user', 'installed history')
    assert handle.sessions.get_messages_as_conversation('installed')[0]['content'] == 'installed history'

backend = sys.argv[3]
if backend == 'sqlite':
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
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from hermes_db.engine import require_postgresql_driver
    from hermes_db.schema import REQUIRED_REVISION
    from hermes_db.postgresql.transactions import Transactions
    from hermes_db.session_store import PostgresSessionStore
    require_postgresql_driver()
    migrations = package.parent / 'migrations'
    config = Config(str(migrations / 'alembic.ini'))
    config.set_main_option('script_location', str(migrations).replace('%', '%%'))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == REQUIRED_REVISION
    assert scripts.get_revision(REQUIRED_REVISION).path
    assert (migrations / 'env.py').is_file()
print(json.dumps({'backend': backend, 'package': str(package), 'sqlite_history': True}))
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
    assert json.loads(result.stdout.splitlines()[-1])['sqlite_history']
