"""RetainDB worker commands keep queue effects and execution receipts in one PG transaction."""

from contextlib import contextmanager
import json
import uuid

import pytest
from sqlalchemy import func, select, update

from hermes_db.errors import UnknownCommitError
from hermes_db.tables.retain_queue import pending
from hermes_state_runtime import RuntimeStoreError
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]
DESTINATION = '1' * 64


def enqueue_payload(content='队列\x00🙂'):
    return dict(destination_id=DESTINATION, request_id=str(uuid.uuid4()), user_id='user\x00雪',
        session_id='remote-session', messages=[{'role': 'user', 'content': content,
            'metadata': {'zero': 0, 'false': False, 'none': None}}])


def test_retain_enqueue_rolls_back_with_receipt_and_recovers_actual_commit_confirmation(pg_store, monkeypatch):
    from hermes_db.domains.runtime.postgres.operations import workers
    runtime, args = assignment(pg_store)
    payload = enqueue_payload()
    command = dict(**args, sequence=1, operation='domain.retain_queue.enqueue', payload=payload)

    def fail_receipt(*params):
        raise RuntimeError('receipt refusal after queue insert')

    with monkeypatch.context() as patch:
        patch.setattr(workers, '_save_receipt', fail_receipt)
        with pytest.raises(RuntimeError, match='receipt refusal'):
            runtime.mutate_worker(**command)
    with pg_store._read() as conn:
        assert conn.scalar(select(func.count()).select_from(pending).where(pending.c.store_id == pg_store.scope.store_id)) == 0
    write = runtime._write

    @contextmanager
    def lose_ack():
        with write() as conn:
            yield conn
        raise UnknownCommitError('lost confirmation after actual queue and receipt commit')

    with monkeypatch.context() as patch:
        patch.setattr(runtime, '_write', lose_ack)
        with pytest.raises(UnknownCommitError):
            runtime.mutate_worker(**command)
    committed = runtime.mutate_worker(**command)
    assert runtime.mutate_worker(**command) == committed
    row = runtime.read_domain('same', 'retain_queue.inspect', {
        'destination_id': DESTINATION, 'request_id': payload['request_id']})['value']
    assert row['user_id'] == payload['user_id']
    assert json.loads(row['messages_json']) == payload['messages']
    assert row['status'] == 'pending'
    with pg_store._read() as conn:
        assert conn.scalar(select(func.count()).select_from(pending).where(pending.c.store_id == pg_store.scope.store_id)) == 1


def test_retain_commands_fence_namespace_token_peer_and_client_scope(pg_pair):
    first, peer = pg_pair
    runtime, args = assignment(first)
    other, other_args = assignment(peer)
    payload = enqueue_payload()
    runtime.mutate_worker(**args, sequence=1, operation='domain.retain_queue.enqueue', payload=payload)
    other.mutate_worker(**other_args, sequence=1, operation='domain.retain_queue.enqueue',
        payload={**payload, 'messages': [{'role': 'user', 'content': 'peer remains pending'}]})
    second = dict(enqueue_payload('another destination'), destination_id='2' * 64)
    runtime.mutate_worker(**args, sequence=2, operation='domain.retain_queue.enqueue', payload=second)
    selected = {'destination_id': DESTINATION}
    assert runtime.read_domain('same', 'retain_queue.ready', selected)['value'] is True
    claimed = runtime.mutate_worker(**args, sequence=3, operation='domain.retain_queue.claim', payload=selected)['value']
    assert claimed['request_id'] == payload['request_id']
    assert claimed['status'] == 'claimed' and claimed['claim_token']
    acknowledgement = dict(selected, request_id=payload['request_id'], token=str(uuid.uuid4()))
    assert runtime.mutate_worker(**args, sequence=4, operation='domain.retain_queue.acknowledge', payload=acknowledgement)['value'] is False
    acknowledgement['token'] = claimed['claim_token']
    ack = dict(**args, sequence=5, operation='domain.retain_queue.acknowledge', payload=acknowledgement)
    assert runtime.mutate_worker(**ack)['value'] is True
    assert runtime.mutate_worker(**ack)['value'] is True
    inspected = dict(selected, request_id=payload['request_id'])
    row = runtime.read_domain('same', 'retain_queue.inspect', inspected)['value']
    assert row['status'] == 'acknowledged' and row['messages_json'] is None
    assert other.read_domain('same', 'retain_queue.inspect', inspected)['value']['status'] == 'pending'
    assert runtime.read_domain('same', 'retain_queue.ready', selected)['value'] is False
    assert runtime.mutate_worker(**args, sequence=6, operation='domain.retain_queue.claim', payload=selected)['value'] is None
    different = runtime.mutate_worker(**args, sequence=7, operation='domain.retain_queue.claim', payload={'destination_id': '2' * 64})['value']
    assert different['request_id'] == second['request_id']
    for extra in ({'store_id': 'other-store'}, {'plugin_id': 'foreign'}, {'lease_until': 9999999999}):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            runtime.mutate_worker(**args, sequence=8, operation='domain.retain_queue.enqueue', payload={**enqueue_payload(), **extra})


def test_lost_renewal_confirmation_never_grants_current_lease_after_retake(pg_store, monkeypatch):
    runtime, args = assignment(pg_store)
    payload = enqueue_payload()
    selected = {'destination_id': DESTINATION}
    runtime.mutate_worker(**args, sequence=1, operation='domain.retain_queue.enqueue', payload=payload)
    row = runtime.mutate_worker(**args, sequence=2, operation='domain.retain_queue.claim', payload=selected)['value']
    token = dict(selected, request_id=payload['request_id'], token=row['claim_token'])
    renewal = dict(**args, sequence=3, operation='domain.retain_queue.renew', payload=token)
    write = runtime._write

    @contextmanager
    def lose_ack():
        with write() as conn:
            yield conn
        raise UnknownCommitError('actual renewal committed without confirmation')

    with monkeypatch.context() as patch:
        patch.setattr(runtime, '_write', lose_ack)
        with pytest.raises(UnknownCommitError):
            runtime.mutate_worker(**renewal)
    with pg_store._write() as conn:
        conn.execute(update(pending).where(pending.c.store_id == pg_store.scope.store_id,
            pending.c.plugin_id == 'retaindb', pending.c.request_id == payload['request_id']).values(lease_until=0))
    pg_store.create_session('replacement-session', 'cli')
    replacement = dict(args, execution_id='replacement-worker', session_id='replacement-session')
    runtime.register_worker(**replacement, kind='compute', adoption_secret='private-replacement')
    retaken = runtime.mutate_worker(**replacement, sequence=1, operation='domain.retain_queue.claim', payload=selected)['value']
    assert retaken['claim_token'] != token['token']
    assert runtime.mutate_worker(**renewal)['value'] is True
    assert runtime.read_domain('same', 'retain_queue.owns_claim', token)['value'] is False
    for sequence, operation, extra in ((4, 'renew', {}), (5, 'fail', {'error': 'stale sender'}), (6, 'acknowledge', {})):
        assert runtime.mutate_worker(**args, sequence=sequence, operation='domain.retain_queue.' + operation,
            payload=dict(token, **extra))['value'] is False
    current = runtime.read_domain('same', 'retain_queue.inspect', {
        **selected, 'request_id': payload['request_id']})['value']
    assert current['status'] == 'claimed' and current['claim_token'] == retaken['claim_token']
