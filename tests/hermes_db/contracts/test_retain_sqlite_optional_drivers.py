"""Actual RetainDB provider/SQLite queue works with every PG dependency blocked."""

import subprocess
import sys


def test_retain_provider_sqlite_without_postgresql_drivers(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import importlib.abc,sys,sqlite3
from threading import Event
from pathlib import Path
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'sqlalchemy','psycopg','alembic'}:
            raise ImportError('PG dependency blocked in native RetainDB contract')
sys.meta_path.insert(0,BlockDrivers())
from plugins.memory import retaindb
done=Event()
class Client:
    def __init__(self,api_key,base_url,project):
        self.base_url,self.project=base_url,project
    def ingest_session(self,user_id,session_id,messages):
        assert user_id=='user' and session_id=='session'
        assert messages[0]['content']=='零\x00🙂'
        done.set()
        return {'status':'ok'}
retaindb._Client=Client
home=Path(sys.argv[1])
provider=retaindb.RetainDBMemoryProvider()
try:
    provider.initialize('session',hermes_home=str(home),user_id='user')
    provider.sync_turn('零\x00🙂','reply')
    assert done.wait(15)
finally:
    provider.shutdown()
conn=sqlite3.connect(home/'retaindb_queue.db')
try:
    assert conn.execute('SELECT count(*) FROM pending').fetchone()[0]==0
finally:
    conn.close()
print('SQLITE_RETAIN_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_RETAIN_STANDALONE_OK" in result.stdout
