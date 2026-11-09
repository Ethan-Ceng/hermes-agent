"""Owner-domain effects share the real PG worker receipt commit and scope fence."""

from contextlib import contextmanager
from datetime import datetime, timedelta, UTC

import pytest
from sqlalchemy import func, select

from hermes_db.errors import UnknownCommitError
from hermes_db.integration.runtime_access import runtime_for_store
from hermes_db.tables.verification import verification_events as events
from hermes_state_runtime import RuntimeStoreError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def assignment(store):
    store.create_session('same', 'cli')
    runtime = runtime_for_store(store)
    epoch = runtime.begin_epoch(instance_id='domain-owner')
    args = dict(epoch=epoch, execution_id='same-worker', session_id='same', generation=0)
    runtime.register_worker(**args, kind='compute', adoption_secret='private-fixture')
    return runtime, args


def request(root):
    return {'evidence': {'session_id': 'same', 'root': str(root), 'cwd': str(root),
        'command': 'pytest -q # \x00雪', 'canonical_command': 'pytest', 'kind': 'test',
        'scope': 'full', 'status': 'passed', 'exit_code': 0, 'output_summary': 'passed'}}


def test_domain_write_and_worker_receipt_survive_rollback_and_lost_commit_ack(pg_pair, tmp_path, monkeypatch):
    from hermes_db.domains.runtime.postgres.operations import workers
    first, peer = pg_pair
    runtime, args = assignment(first)
    peer_runtime, _ = assignment(peer)
    mutation = dict(**args, sequence=1, operation='domain.verification.record', payload=request(tmp_path))
    original = workers._save_receipt

    def fail_receipt(*params):
        raise RuntimeError('receipt refusal after real evidence SQL')

    with monkeypatch.context() as patch:
        patch.setattr(workers, '_save_receipt', fail_receipt)
        with pytest.raises(RuntimeError, match='receipt refusal'):
            runtime.mutate_worker(**mutation)
    assert workers._save_receipt is original
    with first._read() as conn:
        assert conn.scalar(select(func.count()).select_from(events).where(events.c.store_id == first.scope.store_id)) == 0

    write = runtime._context.write

    @contextmanager
    def lose_ack():
        with write() as conn:
            yield conn
        raise UnknownCommitError('lost acknowledgement after actual PG commit')

    with monkeypatch.context() as patch:
        patch.setattr(runtime._context, 'write', lose_ack)
        with pytest.raises(UnknownCommitError):
            runtime.mutate_worker(**mutation)
    committed = runtime.mutate_worker(**mutation)
    assert runtime.mutate_worker(**mutation) == committed
    assert committed['value']['command'] == 'pytest -q # \x00雪'
    with first._read() as conn:
        assert conn.scalar(select(func.count()).select_from(events).where(events.c.store_id == first.scope.store_id)) == 1
    status = runtime.read_domain('same', 'verification.status', {'session_id': 'same', 'root': str(tmp_path)})
    assert status['value']['status'] == 'passed'
    assert status['value']['evidence']['id'] == committed['value']['id']
    other = peer_runtime.read_domain('same', 'verification.status', {'session_id': 'same', 'root': str(tmp_path)})
    assert other['value']['status'] == 'unverified'


def test_worker_domain_rejects_foreign_session_and_client_selected_scope(pg_store, tmp_path):
    from hermes_db.domains.verification.api import record
    from hermes_db.domains.runtime.postgres.operations.worker_domains import ReceiptDomainResource
    runtime, args = assignment(pg_store)
    pg_store.create_session('foreign', 'cli')
    foreign = dict(request(tmp_path)['evidence'], session_id='foreign')
    now = datetime.now(UTC)
    with pg_store._write() as conn:
        record(ReceiptDomainResource(conn, pg_store.scope, writable=True), foreign, now.isoformat(),
            cutoff=(now - timedelta(days=30)).isoformat(), per_root_limit=100, total_limit=10000)
    payload = request(tmp_path)
    payload['evidence']['session_id'] = 'foreign'
    with pytest.raises(RuntimeStoreError, match='permission_denied'):
        runtime.mutate_worker(**args, sequence=1, operation='domain.verification.record', payload=payload)
    with pytest.raises(RuntimeStoreError, match='permission_denied'):
        runtime.read_domain('same', 'verification.status', {'session_id': 'foreign', 'root': str(tmp_path)})
    for forgery in ({'store_id': 'peer-store'}, {'cutoff': '9999-12-31T00:00:00+00:00'},
                    {'per_root_limit': 1}, {'total_limit': 1}, {'created_at': '9999-12-31T00:00:00+00:00'}):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            runtime.mutate_worker(**args, sequence=1, operation='domain.verification.record', payload={**request(tmp_path), **forgery})
    with pytest.raises(RuntimeStoreError, match='invalid_params'):
        runtime.read_domain('same', 'sql.execute', {'sql': 'SELECT 1'})
    runtime.mutate_worker(**args, sequence=1, operation='domain.verification.record', payload=request(tmp_path))
    with pg_store._read() as conn:
        assert conn.scalar(select(func.count()).select_from(events).where(events.c.store_id == pg_store.scope.store_id)) == 2
    assert runtime.read_domain('foreign', 'verification.status', {'session_id': 'foreign', 'root': str(tmp_path)})['value']['status'] == 'passed'
