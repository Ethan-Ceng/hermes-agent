"""Ordinary daemon and adopted compute persist verification through the owner."""

import asyncio
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

import pytest
from sqlalchemy import select

from tests.gateway.fixtures.local_recovery_probe import child_env, rpc, websocket
from tests.hermes_db.postgresql.scenarios.kanban_full_gateway import daemon
from tests.hermes_db.postgresql.scenarios.managed_domains import Model, install_guard, records
from tests.waiting import async_wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize('ignore_user_config', [False, True])
def test_actual_worker_edit_evidence_survives_owner_restart_and_peer_isolation(pg_profiles, tmp_path, ignore_user_config):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db
    from hermes_db.tables.runtime import session_admissions, worker_executions
    from hermes_db.tables.verification import verification_state
    from hermes_db.core.values import encode_text

    guard, audit = install_guard(tmp_path)
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    model.requests = []
    serving = threading.Thread(target=model.serve_forever, daemon=True)
    serving.start()
    try:
        with pg_profiles('one') as home:
            workspace = home / 'workspace'
            workspace.mkdir()
            (workspace / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n', encoding='utf-8')
            target = workspace / 'worker_written.py'

            def reply(body):
                called = {call['function']['name'] for message in body.get('messages', []) for call in message.get('tool_calls', [])}
                offered = {tool['function']['name'] for tool in body.get('tools', [])}
                if 'write_file' in offered and 'write_file' not in called:
                    return {'role': 'assistant', 'content': None, 'tool_calls': [{'index': 0, 'id': 'edit-file', 'type': 'function',
                        'function': {'name': 'write_file', 'arguments': json.dumps({'path': str(target), 'content': "print('worker edit')\n"})}}]}, 'tool_calls'
                return {'role': 'assistant', 'content': 'OWNER_DOMAIN_EDIT_DONE'}, 'stop'

            model.reply = reply
            url = f'http://127.0.0.1:{model.server_port}/v1'
            config = read_user_config_raw(home / 'config.yaml')
            config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
            config.update(gateway={'multiplex_profiles': False, 'managed_workers': True},
                model={'provider': 'custom', 'default': 'domain-loop', 'base_url': url, 'context_length': 65536},
                auxiliary={'title_generation': {'enabled': False}}, platform_toolsets={'cli': ['file']},
                agent={'verify_on_stop': True, 'max_iterations': 8}, telemetry={'shared_metrics': {'enabled': False}})
            atomic_config_write(home / 'config.yaml', config)
            user = tmp_path / 'user'
            user.mkdir()
            env = {**child_env(), 'HOME': str(user), 'USERPROFILE': str(user), 'HERMES_HOME': str(home),
                'HERMES_RUNTIME_DIR': str(home / 'runtime'), 'OPENAI_API_KEY': 'loopback-only', 'OPENAI_BASE_URL': url,
                'PYTHONPATH': os.pathsep.join((str(guard), str(Path(__file__).resolve().parents[3])))}
            if ignore_user_config:
                # The documented launch override opts in while the agent deliberately ignores Profile settings.
                env['HERMES_VERIFY_ON_STOP'] = '1'
            with open_profile_db(home) as inspection, daemon(home, env) as descriptor:
                store = inspection.sessions

                def terminal():
                    with store._transactions.read() as conn:
                        admissions = conn.execute(select(session_admissions.c.status).where(session_admissions.c.store_id == 'one',
                            session_admissions.c.request_id == 'edit-domain')).scalars().all()
                        workers = conn.execute(select(worker_executions.c.status).where(worker_executions.c.store_id == 'one')).scalars().all()
                    return admissions == ['terminal'] and workers and set(workers) == {'terminal'}

                async def run():
                    async with websocket(home, descriptor) as ws:
                        created = await rpc(ws, 'session.create', source='cli', request_id='edit-domain', cwd=str(workspace),
                            toolsets=['file'], provider='custom', model='domain-loop', base_url=url,
                            ignore_user_config=ignore_user_config)
                        sid = created['result']['session_id']
                        submitted = await rpc(ws, 'prompt.submit', session_id=sid, input_id='edit-domain', text='WRITE_FILE_WITH_OWNER_EVIDENCE')
                        assert submitted.get('result', {}).get('status') == 'queued', submitted
                        await async_wait_until(terminal, timeout=90, what='real PG verification worker terminal')
                        await async_wait_until(lambda: any(row['kind'] == 'worker_exit' and descriptor['pid'] in row['ancestors']
                            for row in records(audit)), timeout=20, what='adopted worker graceful exit')
                        resumed = await rpc(ws, 'session.resume', session_id=sid)
                        assert 'OWNER_DOMAIN_EDIT_DONE' in json.dumps(resumed)
                        return sid

                sid = asyncio.run(run())
            assert target.read_text(encoding='utf-8') == "print('worker edit')\n"
            assert model.requests and any(message.get('role') == 'tool' for body in model.requests for message in body.get('messages', []))

            # The original owner and worker have exited; a new ordinary owner must recover it.
            with daemon(home, env) as restarted:
                assert restarted['pid'] != descriptor['pid']

                async def resume():
                    async with websocket(home, restarted) as ws:
                        resumed = await rpc(ws, 'session.resume', session_id=sid)
                        assert 'OWNER_DOMAIN_EDIT_DONE' in json.dumps(resumed)
                asyncio.run(resume())
                with open_profile_db(home) as reopened, reopened.sessions._transactions.read() as conn:
                    state = conn.execute(select(verification_state).where(verification_state.c.store_id == 'one',
                        verification_state.c.session_id == encode_text(sid))).mappings().one()
                    assert state['last_edit_at']
                    assert any(path.endswith('worker_written.py') for path in json.loads(state['changed_paths_json']))
        with pg_profiles('two') as peer, open_profile_db(peer) as other, other.sessions._transactions.read() as conn:
            assert not conn.execute(select(verification_state).where(verification_state.c.store_id == 'two')).first()
        assert not [row for row in records(audit) if row['kind'] == 'sqlite']
    finally:
        model.shutdown()
        serving.join(timeout=5)
        model.server_close()
