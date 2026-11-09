"""Real WebSocket loss at the queue transport seam preserves PG work and journal fences."""

import threading

import pytest
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect
from websockets.sync.server import serve

from agent.runtime_domain_store import WorkerDomainStore
from agent.runtime_session_store import RuntimeSessionStore, WorkerPersistenceError, WorkerRPC, _OwnerLink
from hermes_db.domains.plugin_storage.retain.api import WorkerRetainQueueRef
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from hermes_db.domains.plugin_storage.retain.postgres.queue import PostgresWriteQueue
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment
from tests.waiting import wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize('fault', ['read', 'committed_acknowledgement', 'committed_enqueue'])
def test_websocket_close_preserves_consumer_and_requires_pending_write_reconciliation(pg_store, tmp_path, monkeypatch, fault):
    runtime, scope = assignment(pg_store)
    closed, handled = threading.Event(), threading.Event()
    faults, sent = [], []

    def disconnect(ws):
        ws.recv()
        ws.close(code=1011, reason='controlled transport loss')
        closed.set()

    server = serve(disconnect, '127.0.0.1', 0)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    rpc = WorkerRPC(pg_store.scope.profile_home)
    link = _OwnerLink(connect(f'ws://127.0.0.1:{server.socket.getsockname()[1]}', proxy=None, ping_interval=None))
    monkeypatch.setattr(rpc, '_connection', lambda: link)
    lose_confirmation = True

    def dispatch(method, **params):
        nonlocal lose_confirmation
        if method == 'worker.read':
            assert params['operation'] == 'domain.read'
            payload = params['payload']
            if fault == 'read' and payload['name'] == 'retain_queue.ready' and lose_confirmation:
                lose_confirmation = False
                return rpc(method, **params)
            return runtime.read_domain(params['session_id'], **payload)
        assert method == 'worker.persist'
        result = runtime.mutate_worker(**params)
        operation = {'committed_acknowledgement': 'acknowledge', 'committed_enqueue': 'enqueue'}.get(fault)
        if operation and params['operation'] == 'domain.retain_queue.' + operation and lose_confirmation:
            lose_confirmation = False
            return rpc(method, **params)
        return result

    store = RuntimeSessionStore(dispatch, scope, tmp_path / 'outbox')
    resource = WorkerDomainStore('retain_queue', store, dict(backend='postgresql',
        profile_home=str(pg_store.scope.profile_home), store_id=pg_store.scope.store_id, target='captured-test-owner'))
    reference = WorkerRetainQueueRef(resource, '7' * 64)
    messages = [{'role': 'user', 'content': '持久\x00🙂'}]
    if fault != 'committed_enqueue':
        operations.enqueue(reference, operations.prepare(reference, 'retained-row', 'u', 'old-remote-session', messages))

    class Client:
        base_url, project = 'http://127.0.0.1/test', 'test'

        def ingest_session(self, *args):
            sent.append(args)

    original_wait = PostgresWriteQueue._wait

    def observed_wait(queue):
        handled.set()
        original_wait(queue)

    monkeypatch.setattr(threading, 'excepthook', lambda args: faults.append(args.exc_value))
    monkeypatch.setattr(PostgresWriteQueue, '_wait', observed_wait)
    monkeypatch.setattr('hermes_db.domains.plugin_storage.retain.postgres.queue.capture_queue', lambda *args: reference)
    queue = PostgresWriteQueue(Client(), tmp_path / 'unused.sqlite3', profile_home=pg_store.scope.profile_home)
    try:
        request_id = 'retained-row'
        if fault == 'committed_enqueue':
            with pytest.raises(WebSocketException) as failure:
                queue.enqueue('u', 'old-remote-session', messages)
            request_id = failure.value.request_id
            assert store.journal['pending'][0]['payload']['request_id'] == request_id
        assert closed.wait(timeout=10)
        wait_until(lambda: bool(faults) or handled.is_set(), timeout=10, what='writer handles actual channel loss')
        assert not faults and queue._thread.is_alive()
        if fault == 'read':
            def delivered():
                current = runtime.read_domain('same', 'retain_queue.inspect', {
                    'destination_id': reference.destination_id, 'request_id': 'retained-row'})['value']
                return current['status'] == 'acknowledged' and not store.journal['pending']

            wait_until(delivered, timeout=10, what='read fault recovers committed acknowledgement')
            assert not store.failure
        else:
            assert len(sent) == (0 if fault == 'committed_enqueue' else 1) and store.failure
            assert len(store.journal['pending']) == 1
            assert store.journal['pending'][0]['operation'] == 'domain.retain_queue.' + (
                'enqueue' if fault == 'committed_enqueue' else 'acknowledge')
            with pytest.raises(WorkerPersistenceError):
                store.flush_token_counts()
            with pytest.raises(WorkerPersistenceError):
                store.finish()
            queue.shutdown()
            assert store.journal['pending'], 'shutdown must not bypass a missing receipt'
            receipt = store.retry_pending()[0]['value']
            assert receipt['request_id'] == request_id if fault == 'committed_enqueue' else receipt is True
            assert not store.failure and not store.journal['pending']
        current = runtime.read_domain('same', 'retain_queue.inspect', {
            'destination_id': reference.destination_id, 'request_id': request_id})['value']
        if fault == 'committed_enqueue':
            assert current['status'] == 'pending' and current['messages_json']
        else:
            assert current['status'] == 'acknowledged' and current['messages_json'] is None
        assert len(sent) == (0 if fault == 'committed_enqueue' else 1)
        assert store.finish()['status'] == 'terminal'
    finally:
        queue.shutdown()
        store.close()
        rpc.close()
        server.shutdown()
        serving.join(timeout=5)
