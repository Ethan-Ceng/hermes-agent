"""SQLite room events, replicas and private metadata work without the PG extras."""

import subprocess
import sys


def test_rooms_sqlite_standalone_without_postgresql_drivers(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import importlib.abc, sys
from pathlib import Path
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic'}:
            raise ImportError('optional PostgreSQL dependency unavailable')
sys.meta_path.insert(0, BlockDrivers())
from gateway import hosted_rooms as rooms, hosted_room_replicas as replicas
home = Path(sys.argv[1])
source, target = home / 'source.db', home / 'replica.db'
rooms.create_room(source, room_id='room', name='SQLite', members=[{'profile':'ops','handle':'ops'}], authority_gateway_id='gateway-a')
replicas.initialize_replicas(target)
import re, sqlite3
trace = []
connect = sqlite3.connect
def traced(*args, **kwargs):
    connection = connect(*args, **kwargs)
    connection.set_trace_callback(trace.append)
    return connection
sqlite3.connect = traced
rooms.create_room(source, room_id='second-room', name='second', members=[{'profile':'ops','handle':'ops'}], authority_gateway_id='gateway-a')
rooms.append_event(source, room_id='room', event_id='first', kind='message.user', actor={'kind':'user','id':'u'},
    payload={'text':'中文\u0000', 'zero':0, 'false':False, 'thread_id':'thread'}, authority_gateway_id='gateway-a', authority_epoch=1)
page = rooms.read_events(source, room_id='room')
assert page['events'][0]['payload']['false'] is False
assert replicas.ingest_page(target, room_id='room', room_name='copy', members=[], page=page)['stored_seq'] == 1
assert replicas.replica_state(target, room_id='room')['last_seq'] == 1
record = dict(room_id='room', member_id='m', target_url='https://example.test', target_profile='ops', grant='fixture-grant',
    catalog_json='{}', cancellation_scope_id='scope', trace_id='trace', transport_security='https', status='ready', updated_at=1)
rooms.upsert_room_link_record(source, record=record, max_links=1)
assert rooms.list_room_link_records(source)[0]['grant'] == 'fixture-grant'
assert rooms.room_state(source, room_id='room')['latest_seq'] == 1
from gateway import hosted_room_driver as driver, hosted_room_work_records as work
identity = driver.TaskIdentity('room', 'task', 'thread', 'turn')
driver.admit_task(source, identity, payload={'target_profile':'ops','prompt':'private input','source_event_seq':1}, clock=lambda:10)
lease = driver.acquire_lease(source, room_id='room', gateway_id='gateway-a', authority_epoch=1, process_generation='process', ttl_seconds=30, clock=lambda:10)
attempt = driver.start_task(source, identity, lease, expected_cancel_generation=0, clock=lambda:10)
driver.settle_task(source, attempt, settlement_id='receipt', status='settled', result={'zero':0,'false':False}, clock=lambda:10)
assert driver.get_task(source, identity)['result'] == {'zero':0,'false':False}
record = work.capture(source, room_id='room', local_gateway_id='gateway-a')
assert record['tasks'][0]['phase'] == 'settled' and 'private input' not in work.encode(record)
pending = work.prepare_delivery(source, room_id='room', local_gateway_id='gateway-a', target_install_id='peer', route_generation='route', through_seq=1)
assert work.acknowledge(source, room_id='room', target_install_id='peer', route_generation='route', record=pending, ack=work.acknowledgement(pending))
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from tui_gateway.hosted_room_router_call import RouterCalls
checkpoint = HostedRoomPolicyCheckpoint(source)
assert checkpoint.snapshot(room_id='room', latest_seq=1).events[0]['payload']['thread_id'] == 'thread'
router = RouterCalls(source, clock=lambda:10)
assert router._claim(('room','source'))
router._release(('room','source'))
from gateway.hosted_room_attachments import HostedRoomAttachmentStore
files = HostedRoomAttachmentStore(source)
saved = files.put(room_id='room', upload_id='upload', kind='file', name='exact.bin', mime='application/octet-stream', data=b'\x00\xffexact')
manifest = [{key:saved[key] for key in ('attachment_id','kind','name','size','mime')}]
files.commit_message(room_id='room', event_id='file-event', manifest=manifest, recipient_member_ids=['ops'])
assert files.read(room_id='room', event_id='file-event', attachment_id=saved['attachment_id'], recipient_member_id='ops').data == b'\x00\xffexact'
assert trace
assert not [statement for statement in trace if re.match(r"\s*(CREATE|ALTER|DROP|REINDEX)\b", statement, re.IGNORECASE)]
print('SQLITE_ROOMS_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=env, capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_ROOMS_STANDALONE_OK" in result.stdout
