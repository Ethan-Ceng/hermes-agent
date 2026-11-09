"""Actual adopted RetainDB sync, HTTP outside PG, and cross-session restart replay."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

import pytest
from sqlalchemy import select, update

from tests.gateway.fixtures.local_recovery_probe import child_env, rpc, websocket
from tests.hermes_db.postgresql.scenarios.kanban_full_gateway import daemon
from tests.hermes_db.postgresql.scenarios.managed_domains import Model, install_guard, records
from tests.waiting import async_wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


class Memory(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, body, status=200):
        data = json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # The shutdown fault deliberately retires the worker before its response arrives.
            assert self.server.release.is_set()

    def do_GET(self):
        self.respond({'memories': [], 'profile': {}, 'memory_count': 0})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/v1/memory/ingest/session':
            self.server.ingests.append(body)
            if not self.server.accept.is_set():
                self.server.waiting.set()
                assert self.server.release.wait(timeout=45), 'test did not release real RetainDB HTTP'
                self.respond({'error': 'controlled unavailability'}, 503)
                return
        self.respond({'results': [], 'context': '', 'memory_count': 0, 'status': 'ok'})


@pytest.mark.parametrize('abandon_http', [False, True])
def test_managed_sync_persists_before_http_and_new_owner_worker_replays_same_pending(pg_profiles, tmp_path, abandon_http):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db
    from hermes_db.tables.retain_queue import pending
    from hermes_db.tables.runtime import session_admissions, worker_executions
    from hermes_db.core.values import decode_text

    guard, audit = install_guard(tmp_path)
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    model.requests = []
    model.reply = lambda body: ({'role': 'assistant', 'content': 'RETAIN_OWNER_SYNC_DONE'}, 'stop')
    memory = ThreadingHTTPServer(('127.0.0.1', 0), Memory)
    memory.ingests = []
    memory.waiting, memory.release, memory.accept = threading.Event(), threading.Event(), threading.Event()
    servers = (model, memory)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        with pg_profiles('one') as home:
            workspace = home / 'workspace'
            workspace.mkdir()
            url = f'http://127.0.0.1:{model.server_port}/v1'
            config = read_user_config_raw(home / 'config.yaml')
            config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
            config.update(gateway={'multiplex_profiles': False, 'managed_workers': True},
                model={'provider': 'custom', 'default': 'retain-loop', 'base_url': url, 'context_length': 65536},
                memory={'provider': 'retaindb', 'retaindb': {'base_url': f'http://127.0.0.1:{memory.server_port}', 'project': 'owned-test'}},
                auxiliary={'title_generation': {'enabled': False}}, platform_toolsets={'cli': []},
                agent={'max_iterations': 8}, telemetry={'shared_metrics': {'enabled': False}})
            atomic_config_write(home / 'config.yaml', config)
            user = tmp_path / 'user'
            user.mkdir()
            env = {**child_env(), 'HOME': str(user), 'USERPROFILE': str(user), 'HERMES_HOME': str(home),
                'HERMES_RUNTIME_DIR': str(home / 'runtime'), 'OPENAI_API_KEY': 'loopback-only', 'OPENAI_BASE_URL': url,
                'RETAINDB_API_KEY': 'loopback-only',
                'PYTHONPATH': os.pathsep.join((str(guard), str(Path(__file__).resolve().parents[3])))}
            with open_profile_db(home) as inspection:
                store = inspection.sessions

                def rows():
                    with store._transactions.read() as conn:
                        return [dict(row) for row in conn.execute(select(pending).where(
                            pending.c.store_id == 'one', pending.c.plugin_id == 'retaindb')).mappings()]

                def terminal(request_id):
                    with store._transactions.read() as conn:
                        admissions = conn.execute(select(session_admissions.c.status).where(session_admissions.c.store_id == 'one',
                            session_admissions.c.request_id == request_id)).scalars().all()
                        workers = conn.execute(select(worker_executions.c.status).where(worker_executions.c.store_id == 'one')).scalars().all()
                    return admissions == ['terminal'] and workers and set(workers) == {'terminal'}

                async def turn(descriptor, request_id, *, hold_http=False):
                    async with websocket(home, descriptor) as ws:
                        created = await rpc(ws, 'session.create', source='cli', request_id=request_id, cwd=str(workspace),
                            toolsets=[], provider='custom', model='retain-loop', base_url=url)
                        assert 'result' in created, created
                        sid = created['result']['session_id']
                        response = await rpc(ws, 'prompt.submit', session_id=sid, input_id=request_id, text=request_id)
                        assert response.get('result', {}).get('status') == 'queued', response
                        if hold_http:
                            await async_wait_until(memory.waiting.is_set, timeout=90, what='actual provider sync HTTP')
                            committed = rows()
                            assert len(committed) == 1 and committed[0]['status'] == 'claimed'
                            assert request_id in decode_text(committed[0]['messages_json'])
                            # This owner has only one PG connection; the same owner's public read must finish during HTTP.
                            resumed = await asyncio.wait_for(rpc(ws, 'session.resume', session_id=sid), timeout=10)
                            assert 'RETAIN_OWNER_SYNC_DONE' in json.dumps(resumed)
                            if not abandon_http:
                                memory.release.set()
                        await async_wait_until(lambda: terminal(request_id), timeout=90, what='RetainDB adopted worker terminal')
                        await async_wait_until(lambda: any(row['kind'] == 'worker_exit' and descriptor['pid'] in row['ancestors']
                            for row in records(audit)), timeout=20, what='RetainDB worker graceful exit')
                        resumed = await rpc(ws, 'session.resume', session_id=sid)
                        assert 'RETAIN_OWNER_SYNC_DONE' in json.dumps(resumed)
                        return sid

                with daemon(home, env) as original:
                    first_sid = asyncio.run(turn(original, 'RETAIN_FIRST_DURABLE', hold_http=True))
                retained = rows()
                assert len(retained) == 1 and retained[0]['status'] == ('claimed' if abandon_http else 'pending')
                request_id = retained[0]['request_id']
                first_wire = memory.ingests[0]
                assert first_wire['session_id'] == first_sid and first_wire['project'] == 'owned-test'
                if abandon_http:
                    assert memory.waiting.is_set() and not memory.release.is_set()
                    # Both original processes exited; expire only our owned row to exercise the next claimant immediately.
                    with store._transactions.write() as conn:
                        conn.execute(update(pending).where(pending.c.store_id == 'one', pending.c.plugin_id == 'retaindb',
                            pending.c.request_id == request_id).values(lease_until=0))
                memory.release.set()
                memory.accept.set()
                with daemon(home, env) as restarted:
                    assert restarted['pid'] != original['pid']
                    second_sid = asyncio.run(turn(restarted, 'RETAIN_SECOND_RECOVERY'))
                    assert second_sid != first_sid
                recovered = rows()
                assert len(recovered) == 2 and {row['status'] for row in recovered} == {'acknowledged'}
                assert any(row['request_id'] == request_id for row in recovered)
                assert all(row['messages_json'] is None for row in recovered)
                assert sum(body == first_wire for body in memory.ingests) >= 2
        with pg_profiles('two') as peer, open_profile_db(peer) as other, other.sessions._transactions.read() as conn:
            assert not conn.execute(select(pending).where(pending.c.store_id == 'two')).first()
        assert not [row for row in records(audit) if row['kind'] == 'sqlite']
    finally:
        memory.release.set()
        for server, thread in zip(servers, threads):
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
