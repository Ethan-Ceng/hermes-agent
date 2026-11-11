"""Native Discord recovery stays independent of PostgreSQL libraries."""

import subprocess
import sys


def test_discord_ledger_sqlite_without_postgresql_drivers(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import importlib.abc,sys
from datetime import datetime,UTC
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'sqlalchemy','psycopg','alembic'}:
            raise ImportError('PG imports blocked in native Discord contract')
sys.meta_path.insert(0,BlockDrivers())
from plugins.platforms.discord.recovery import DiscordRecoveryStore, initialize_recovery_schema
initialize_recovery_schema()
stamp=datetime.now(UTC).isoformat()
store=DiscordRecoveryStore()
row=dict(message_id='message',channel_id='channel',thread_id=None,parent_channel_id=None,author_id='author',created_at=stamp,status='queued',updated_at=stamp)
store.attempt(row,error=None)
store.complete('message',success=True,cancelled=False,now=stamp)
store.attempt(row,error=None)
assert DiscordRecoveryStore().is_complete('message')
store.response('message',response_id='reply',completed=True,now=stamp)
assert DiscordRecoveryStore().cursor('channel')=='message'
print('SQLITE_DISCORD_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_DISCORD_STANDALONE_OK" in result.stdout
