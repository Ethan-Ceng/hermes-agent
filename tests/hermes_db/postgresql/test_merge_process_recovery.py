"""New admission tombstones and grant debts survive actual process replacement."""

import json
from pathlib import Path
import subprocess
import sys
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

_PROBE = r'''
import json, os, sys, time
from pathlib import Path
source, home = map(Path, sys.argv[1:3])
kind, phase = sys.argv[3:]
sys.path.insert(0, str(source))
os.environ['HERMES_HOME'] = str(home)
attempts = []
def reject_sqlite(event, args):
    if event == 'sqlite3.connect':
        attempts.append(True)
        raise AssertionError('SQLite forbidden in PG recovery process')
sys.addaudithook(reject_sqlite)
try:
    if kind == 'closed':
        from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
        from hermes_db.integration.run_resources import ProfileRunStores
        with_store = ProfileRunStores(RunIdempotencyStore)
        try:
            if phase == 'write':
                assert with_store.find_or_close('recovery-scope', 'attempt') == ('closed', None)
            else:
                assert with_store.reserve('recovery-scope', 'attempt', 'late', 'late-run', {'status': 'running'})[0] == 'conflict'
                assert with_store.find_or_close('recovery-scope', 'attempt') == ('closed', None)
        finally:
            with_store.close()
    else:
        from gateway import hosted_rooms as rooms
        location = rooms.default_db_path()
        if phase == 'write':
            rooms.create_room(location, room_id='restart-room', name='Room', members=[{'profile': 'ops', 'handle': 'ops'}],
                              authority_gateway_id='owner')
            rooms.owe_room_grant_revoke(location, room_id='restart-room', member_id='ops',
                target_url='http://127.0.0.1:9121', grant='test-owned-token', expires_at=time.time() + 600)
        else:
            assert rooms.room_state(location, room_id='restart-room')['name'] == 'Room'
            debt, = rooms.due_room_grant_revokes(location, limit=10)
            assert debt['room_id'] == 'restart-room' and debt['grant'] == 'test-owned-token'
            assert debt['attempts'] == 0
        from hermes_db.access import close_session_resources
        close_session_resources()
    assert not attempts
    print(json.dumps({'ok': True, 'pid': os.getpid(), 'kind': kind, 'phase': phase}))
except Exception as error:
    print(json.dumps({'ok': False, 'kind': kind, 'phase': phase, 'error_type': type(error).__name__}))
    sys.exit(1)
'''


@pytest.mark.parametrize('kind', ['closed', 'debt'])
def test_merge_state_survives_new_process_with_sqlite_rejected(pg_profiles, tmp_path, kind):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    source = Path(__file__).parents[3]
    with pg_profiles('one') as home:
        outputs = []
        for phase in ('write', 'read'):
            result = subprocess.run([sys.executable, '-I', '-c', _PROBE, str(source), str(home), kind, phase],
                cwd=tmp_path, env={**child_env(), 'HERMES_HOME': str(home), 'HERMES_RUNTIME_DIR': str(home / 'runtime')},
                capture_output=True, text=True, timeout=60, check=False)
            assert result.returncode == 0, result.stdout
            outputs.append(json.loads(result.stdout.strip().splitlines()[-1]))
        assert outputs[0]['ok'] and outputs[1]['ok'] and outputs[0]['pid'] != outputs[1]['pid']
    with pg_profiles('two'):
        from gateway import hosted_rooms as rooms
        from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
        from hermes_db.integration.run_resources import ProfileRunStores
        assert not rooms.owes_room_grant_revokes(rooms.default_db_path())
        resources = ProfileRunStores(RunIdempotencyStore)
        try:
            assert resources.reserve('recovery-scope', 'attempt', 'own', 'own-run', {'status': 'running'})[0] == 'created'
        finally:
            resources.close()
