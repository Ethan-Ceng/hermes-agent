"""Real live-child claim and PG receipt replay through the owner handler, without a WebSocket."""

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_postcommit_maintenance_failure_preserves_journal_and_cached_replay_runs_it_again(pg_profiles, tmp_path, monkeypatch):
    from agent.runtime_session_store import RuntimeSessionStore, WorkerPersistenceError
    from gateway.config import Platform
    from gateway.session_authority import LiveSession, SessionAuthority
    from gateway.session_contract import SessionActor, SessionRef
    from gateway.session_worker import worker_request
    from gateway import session_worker_metrics
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import _owning_profile, open_profile_db
    from hermes_cli.process_identity import worker_birth
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_db.tables.runtime import worker_executions, worker_receipts

    with pg_profiles('one') as home:
        config = read_user_config_raw(home / 'config.yaml')
        config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
        config['telemetry'] = {'shared_metrics': {'enabled': False, 'send': False}}
        atomic_config_write(home / 'config.yaml', config)
    with pg_profiles('two') as foreground:
        child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        worker = None
        try:
            with _owning_profile(home), open_profile_db(home) as selected:
                db = selected.sessions
                db.create_session('owned', 'telegram')
                runtime = runtime_for_store(db)
                epoch = runtime.begin_epoch(instance_id='maintenance')
                runner = SimpleNamespace(_draining=False, config=SimpleNamespace(multiplex_profiles=False),
                    _adapter_for_source=lambda source: None)
                authority = SessionAuthority(runner, profile_id=str(home), instance_id='maintenance', db=db, epoch=epoch)
                authority.sessions['owned'] = LiveSession(SimpleNamespace(platform=Platform.TELEGRAM, user_id='human'), 'route')
                ref = SessionRef(str(home), 'owned')
                connection = SimpleNamespace(authority=authority,
                    actor=SessionActor('human', str(home), frozenset({'worker:adopt'}), 'private-test-ticket'))
                identity = dict(profile_id=str(home), session_id='owned', execution_id='owned-worker', generation=0,
                    pid=child.pid, birth=worker_birth(psutil.Process(child.pid)), secret='private-test-claim-' * 2)
                registered = asyncio.run(worker_request(connection, ref, identity | {'kind': 'compute'}, operation='register'))
                adopted = asyncio.run(worker_request(connection, ref, identity, operation='adopt'))
                assert registered['status'] == 'registered' and adopted['status'] == 'running'
                calls = []
                real_maintain = session_worker_metrics.maintain

                def fail_after_maintenance(store):
                    assert store is db and db._transactions.engine.pool.checkedout() == 0
                    real_maintain(store)
                    assert db._transactions.engine.pool.checkedout() == 0
                    calls.append(True)
                    if len(calls) == 1:
                        raise OSError('postcommit maintenance confirmation failure')

                monkeypatch.setattr(session_worker_metrics, 'maintain', fail_after_maintenance)

                def dispatch(method, **params):
                    assert method == 'worker.persist'
                    return asyncio.run(worker_request(connection, ref, params, operation='persist'))

                worker = RuntimeSessionStore(dispatch, identity | {'epoch': epoch}, tmp_path / 'journal')
                with _owning_profile(foreground), pytest.raises(OSError, match='postcommit maintenance'):
                    worker._apply('domain.metrics.flush', {})
                assert json.loads(worker.path.read_text(encoding='utf-8'))['pending'] == [
                    {'sequence': 1, 'operation': 'domain.metrics.flush', 'payload': {}}]
                with db._read() as conn:
                    cached = conn.execute(select(worker_receipts.c.result_json).where(worker_receipts.c.store_id == 'one',
                        worker_receipts.c.execution_id == 'owned-worker', worker_receipts.c.sequence == 1)).scalar_one()
                    current = conn.execute(select(worker_executions.c.status, worker_executions.c.last_sequence).where(
                        worker_executions.c.store_id == 'one', worker_executions.c.execution_id == 'owned-worker')).one()
                assert current == ('running', 1)
                with pytest.raises(WorkerPersistenceError):
                    worker.finish()
                with _owning_profile(foreground):
                    assert worker.retry_pending() == [json.loads(cached)]
                assert len(calls) == 2 and not worker.failure and not worker.journal['pending']
                with db._read() as conn:
                    rows = conn.execute(select(worker_receipts.c.sequence, worker_receipts.c.result_json).where(
                        worker_receipts.c.store_id == 'one', worker_receipts.c.execution_id == 'owned-worker')).all()
                assert rows == [(1, cached)]
                assert worker.finish()['status'] == 'terminal'
        finally:
            if worker is not None:
                worker.close()
            child.stdin.close()
            child.wait(timeout=5)
