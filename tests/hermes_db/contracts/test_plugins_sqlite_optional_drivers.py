"""Portable plugin records remain useful in an independently usable SQLite installation."""

import subprocess
import sys


def test_portable_plugin_sqlite_without_postgresql_drivers(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import importlib.abc,sys
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy','psycopg','alembic'}:
            raise ImportError('PG driver blocked in standalone plugin contract')
sys.meta_path.insert(0,BlockDrivers())
from plugins.plugin_storage import plugin_store, initialize_plugin_store,PluginStorageConflict
initialize_plugin_store('example')
saved=plugin_store('example').put('key\x00',{'value':'零\x00🙂'},expected_revision=0)
store=plugin_store('example')
assert store.get(saved.key)==saved
assert store.delete(saved.key,expected_revision=saved.revision)
current=store.put(saved.key,False,expected_revision=0)
assert current.revision>saved.revision
try:
    store.put(saved.key,'wrong',expected_revision=saved.revision)
except PluginStorageConflict:
    pass
else:
    raise AssertionError('stale revision accepted')
assert store.scan()[0].value is False
print('SQLITE_PLUGIN_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_PLUGIN_STANDALONE_OK" in result.stdout
