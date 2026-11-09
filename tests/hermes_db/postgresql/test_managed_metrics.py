"""Actual worker metrics use the adopted PG dataset and the owner's send consent."""

import asyncio
from datetime import datetime, timedelta, UTC
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        self.server.received.append(json.loads(gzip.decompress(raw) if self.headers.get('Content-Encoding') == 'gzip' else raw))
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()


@pytest.mark.parametrize('ignore_user_config', [False, True])
def test_worker_counters_and_engagement_recover_without_changing_owner_consent(pg_profiles, tmp_path, monkeypatch, ignore_user_config):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db
    from hermes_cli.observability.shared_metrics import SharedMetricsStore
    from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC, MODEL_ROUTE_METRIC
    from hermes_cli.observability.shared_metrics_engagement import STATE_KEY
    from hermes_db.tables.metrics import state, windows
    from hermes_db.tables.runtime import session_admissions, worker_executions
    from hermes_db.core.values import decode_text, encode_text
    from tests.hermes_db.postgresql.test_metrics_store import RESOURCE

    guard, audit = install_guard(tmp_path)
    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    model.requests = []
    model.reply = lambda body: ({'role': 'assistant', 'content': 'OWNER_METRICS_MODEL_DONE'}, 'stop')
    receiver = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    receiver.received = []
    servers = (model, receiver)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        with pg_profiles('one') as home:
            url = f'http://127.0.0.1:{model.server_port}/v1'
            config = read_user_config_raw(home / 'config.yaml')
            config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
            config.update(gateway={'multiplex_profiles': False, 'managed_workers': True},
                model={'provider': 'custom', 'default': 'metrics-loop', 'base_url': url, 'context_length': 65536},
                auxiliary={'title_generation': {'enabled': False}}, platform_toolsets={'cli': []},
                telemetry={'shared_metrics': {'enabled': True, 'send': ignore_user_config,
                    'endpoint': f'http://127.0.0.1:{receiver.server_port}/metrics'}})
            atomic_config_write(home / 'config.yaml', config)
            legacy = home / 'telemetry/shared_metrics/metrics.sqlite3'
            legacy.parent.mkdir(parents=True)
            legacy_bytes = b'SQLite format 3\x00' + bytes(4096 - 16)
            legacy.write_bytes(legacy_bytes)
            metrics = SharedMetricsStore(profile_home=home)
            if ignore_user_config:
                from hermes_cli.observability import shared_metrics as native
                day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
                metrics.reconcile_send_consent(True, now=day - timedelta(days=1))
                with monkeypatch.context() as patch:
                    patch.setattr(native, '_utc_now', lambda: day + timedelta(hours=12))
                    metrics.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
                metrics.reconcile_send_consent(True, now=day)
                metrics.reconcile_send_consent(True, now=day + timedelta(days=1))
            else:
                metrics.reconcile_send_consent(True)
            user = tmp_path / 'user'
            user.mkdir()
            env = {**child_env(), 'HOME': str(user), 'USERPROFILE': str(user), 'HERMES_HOME': str(home),
                'HERMES_RUNTIME_DIR': str(home / 'runtime'), 'OPENAI_API_KEY': 'loopback-only', 'OPENAI_BASE_URL': url,
                'PYTHONPATH': os.pathsep.join((str(guard), str(Path(__file__).resolve().parents[3])))}
            with open_profile_db(home) as inspection:
                store = inspection.sessions

                def terminal():
                    with store._transactions.read() as conn:
                        admissions = conn.execute(select(session_admissions.c.status).where(session_admissions.c.store_id == 'one',
                            session_admissions.c.request_id == 'model-metrics')).scalars().all()
                        workers = conn.execute(select(worker_executions.c.status).where(worker_executions.c.store_id == 'one')).scalars().all()
                    return admissions == ['terminal'] and workers and set(workers) == {'terminal'}

                with daemon(home, env) as original:
                    async def run():
                        async with websocket(home, original) as ws:
                            response = await rpc(ws, 'session.create', source='cli', request_id='model-metrics', toolsets=[],
                                provider='custom', model='metrics-loop', base_url=url, ignore_user_config=ignore_user_config)
                            assert 'result' in response, response
                            sid = response['result']['session_id']
                            queued = await rpc(ws, 'prompt.submit', session_id=sid, input_id='model-metrics', text='PERSIST_ACTUAL_MODEL_METRICS')
                            assert queued.get('result', {}).get('status') == 'queued', queued
                            await async_wait_until(terminal, timeout=90, what='PG metrics managed worker terminal')
                            await async_wait_until(lambda: any(row['kind'] == 'worker_exit' and original['pid'] in row['ancestors']
                                for row in records(audit)), timeout=20, what='PG metrics worker graceful exit')
                            resumed = await rpc(ws, 'session.resume', session_id=sid)
                            assert 'OWNER_METRICS_MODEL_DONE' in json.dumps(resumed)
                            return sid

                    sid = asyncio.run(run())
                with daemon(home, env) as restarted:
                    assert restarted['pid'] != original['pid']

                    async def resume():
                        async with websocket(home, restarted) as ws:
                            assert 'OWNER_METRICS_MODEL_DONE' in json.dumps(await rpc(ws, 'session.resume', session_id=sid))

                    asyncio.run(resume())
                snapshot = SharedMetricsStore(profile_home=home).counter_snapshot()
                calls = sum(row['value'] for row in snapshot if row['metric_name'] == MODEL_ROUTE_METRIC)
                assert calls == (0 if ignore_user_config else 1), f'Actual model calls persisted after restart: {calls}'
                with store._transactions.read() as conn:
                    consent = conn.execute(select(windows.c.closed_at).where(windows.c.store_id == 'one',
                        windows.c.closed_at.is_(None))).all()
                    rollup = conn.scalar(select(state.c.value).where(state.c.store_id == 'one', state.c.key == encode_text(STATE_KEY)))
                assert bool(consent) is ignore_user_config, 'Agent defaults must not revoke the owner send window'
                if ignore_user_config:
                    assert any(packet['period_start'].startswith(day.date().isoformat()) for packet in receiver.received)
                else:
                    assert receiver.received == []
                if not ignore_user_config:
                    assert rollup is not None and sum(json.loads(decode_text(rollup))['models'].values()) == 1
            assert legacy.read_bytes() == legacy_bytes
        with pg_profiles('two') as peer:
            assert not SharedMetricsStore(profile_home=peer).counter_snapshot()
            with open_profile_db(peer) as other:
                assert other.sessions.get_session(sid) is None
        assert not [row for row in records(audit) if row['kind'] == 'sqlite']
    finally:
        for server, thread in zip(servers, threads):
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
