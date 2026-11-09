"""Real Relay subscriber plus canonical PG effects at the compute barrier seam."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from agent import relay_runtime
from agent.runtime_domain_store import WorkerDomainStore, owner_binding
from agent.runtime_session_store import RuntimeSessionStore, WorkerPersistenceError
from gateway.session_worker_domains import storage_identity
from hermes_cli.observability import relay_shared_metrics as shared
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_MARK
from hermes_cli.observability.worker_metrics_shutdown import quiesce
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.runtime.postgres.metrics import WorkerMetricsStore
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize('lose_confirmation', [False, True])
def test_actual_sdk_subscriber_settles_before_finish_and_lost_commit_cannot_report_success(pg_profiles, tmp_path, monkeypatch, lose_confirmation):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db

    entered, release, flushing = threading.Event(), threading.Event(), threading.Event()
    with pg_profiles('one') as home:
        config = read_user_config_raw(home / 'config.yaml')
        config['telemetry'] = {'shared_metrics': {'enabled': True, 'send': False}}
        atomic_config_write(home / 'config.yaml', config)
        with open_profile_db(home) as owner:
            canonical, scope = assignment(owner.sessions)
            lose = lose_confirmation

            def dispatch(method, **params):
                nonlocal lose
                if method == 'worker.read':
                    if params['operation'] == 'storage.identity':
                        return storage_identity(owner.sessions)
                    return canonical.read_domain(params['session_id'], **params['payload'])
                assert method == 'worker.persist'
                if params['operation'] == 'domain.metrics.active':
                    entered.set()
                    assert release.wait(timeout=20)
                result = canonical.mutate_worker(**params)
                if params['operation'] == 'domain.metrics.active' and lose:
                    lose = False
                    raise UnknownCommitError('actual metric and receipt commit lost confirmation')
                return result

            store = RuntimeSessionStore(dispatch, scope, tmp_path / 'outbox')
            binding = owner_binding(store)
            proxy = object.__new__(WorkerMetricsStore)
            proxy.reference = WorkerDomainStore('metrics', store, binding)
            proxy.profile_home, proxy.database_path, proxy.outbox_directory = home, None, None
            monkeypatch.setattr(shared, 'SharedMetricsStore', lambda: proxy)
            monkeypatch.setattr(shared, '_RUNTIMES', {})
            host = relay_runtime.RelayRuntime(profile_key=str(home.resolve()))
            runtime = shared._get_runtime(host=host)
            assert isinstance(runtime, shared._Runtime)
            flush = runtime.relay.subscribers.flush

            def observed_flush():
                flushing.set()
                return flush()

            monkeypatch.setattr(runtime.relay.subscribers, 'flush', observed_flush)
            try:
                runtime.record_process_mark(CLIENT_ACTIVE_MARK, {})
                assert entered.wait(timeout=20)

                def finish_metrics():
                    caller = relay_runtime.current_profile_key()
                    assert caller != str(home.resolve())
                    try:
                        quiesce(store)
                    finally:
                        assert relay_runtime.current_profile_key() == caller

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(finish_metrics)
                    try:
                        assert flushing.wait(timeout=10)
                        assert not future.done(), 'An unsettled SDK subscriber cannot pass the barrier'
                    finally:
                        release.set()
                    if lose_confirmation:
                        with pytest.raises(WorkerPersistenceError):
                            future.result(timeout=30)
                        assert store.journal['pending'] and store.failure
                        with pytest.raises(WorkerPersistenceError):
                            store.finish()
                        store.retry_pending()
                        quiesce(store)
                    else:
                        future.result(timeout=30)
                snapshot = canonical.read_domain('same', 'metrics.snapshot', {})['value']
                assert sum(row['value'] for row in snapshot if row['metric_name'] == CLIENT_ACTIVE_MARK) == 1
                assert not store.journal['pending'] and not store.failure
                assert store.finish()['status'] == 'terminal'
            finally:
                release.set()
                runtime.deactivate()
                host.shutdown()
                store.close()
