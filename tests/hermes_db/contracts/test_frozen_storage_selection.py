"""A backend-only probe honors worker config without hydrating Profile files or drivers."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('policy', ['ordinary', 'ignore', 'safe'])
@pytest.mark.parametrize('backend', ['sqlite', 'postgresql'])
def test_frozen_backend_probe_never_reads_profile_config_or_secrets(tmp_path, policy, backend):
    home, user = tmp_path / 'profile', tmp_path / 'user'
    home.mkdir()
    user.mkdir()
    (home / 'config.yaml').write_text('storage: [broken-profile-value', encoding='utf-8')
    (home / '.env').write_text('FROZEN_SELECTION_SECRET=private-value\n', encoding='utf-8')
    code = r'''
import importlib.abc
import os
from pathlib import Path
import sys
from agent.safe_worker_policy import _bind_worker_config, _bind_safe_worker_policy
home, policy, backend = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
config = {'storage': {'backend': backend}}
if policy == 'ordinary':
    _bind_worker_config(config)
else:
    _bind_safe_worker_policy(safe_mode=policy == 'safe', ignore_user_config=True, config=config)

class NoPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'psycopg', 'sqlalchemy', 'alembic'}:
            raise AssertionError('a backend probe must not import PostgreSQL drivers')
sys.meta_path.insert(0, NoPostgres())
forbidden = {home / 'config.yaml', home / '.env'}
def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve() in forbidden:
            raise AssertionError('frozen backend probe opened a Profile config or secret file')
sys.addaudithook(audit)
from hermes_cli.db_setup import storage_backend
from hermes_constants import get_hermes_home
assert get_hermes_home() == home
assert storage_backend(home) == backend
assert storage_backend() == backend
assert get_hermes_home() == home
'''
    env = {**os.environ, 'HERMES_HOME': str(home), 'HOME': str(user), 'USERPROFILE': str(user)}
    result = subprocess.run([sys.executable, '-c', code, str(home), policy, backend],
        cwd=Path(__file__).resolve().parents[3], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
