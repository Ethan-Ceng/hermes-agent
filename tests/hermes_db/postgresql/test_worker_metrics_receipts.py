"""Worker metrics share canonical PG receipt commits and reject client ownership/policy."""

from contextlib import contextmanager

import pytest
from sqlalchemy import select

from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_db.errors import UnknownCommitError
from hermes_db.tables.metrics import counters
from hermes_state_runtime import RuntimeStoreError
from tests.hermes_db.postgresql.test_metrics_store import RESOURCE
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def counter():
    return dict(metric_name=CLIENT_ACTIVE_METRIC, dimensions={}, resource=RESOURCE, amount=1)


def test_metric_effect_receipt_rollback_actual_commit_loss_and_peer_scope(pg_pair, monkeypatch):
    from hermes_db.domains.runtime.postgres.operations import workers

    first, peer = pg_pair
    runtime, args = assignment(first)
    other, _ = assignment(peer)
    command = dict(**args, sequence=1, operation='domain.metrics.counter', payload=counter())

    def refuse_receipt(*args):
        raise RuntimeError('receipt failed after actual metric effect')

    with monkeypatch.context() as patch:
        patch.setattr(workers, '_save_receipt', refuse_receipt)
        with pytest.raises(RuntimeError, match='receipt failed'):
            runtime.mutate_worker(**command)
    with first._read() as conn:
        assert not conn.execute(select(counters).where(counters.c.store_id == first.scope.store_id)).first()
    write = runtime._write

    @contextmanager
    def lose_confirmation():
        with write() as conn:
            yield conn
        raise UnknownCommitError('metric and receipt actually committed')

    with monkeypatch.context() as patch:
        patch.setattr(runtime, '_write', lose_confirmation)
        with pytest.raises(UnknownCommitError):
            runtime.mutate_worker(**command)
    receipt = runtime.mutate_worker(**command)
    assert runtime.mutate_worker(**command) == receipt
    snapshot = runtime.read_domain('same', 'metrics.snapshot', {})['value']
    assert len(snapshot) == 1 and snapshot[0]['value'] == 1 and snapshot[0]['resource'] == RESOURCE
    assert other.read_domain('same', 'metrics.snapshot', {})['value'] == []


def test_worker_cannot_supply_metric_dataset_clock_latch_or_consent_policy(pg_store):
    runtime, args = assignment(pg_store)
    for extra in ({'store_id': 'foreign'}, {'profile_home': '/foreign'}, {'now': '2099-01-01'}, {'state_key': 'install_id'}):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            runtime.mutate_worker(**args, sequence=1, operation='domain.metrics.counter', payload={**counter(), **extra})
    for payload in ({'send_enabled': True}, {'now': '2099-01-01'}):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            runtime.mutate_worker(**args, sequence=1, operation='domain.metrics.consent', payload=payload)


def test_named_worker_interval_feature_and_daily_latches_use_owner_age_and_stay_durable(pg_store):
    runtime, args = assignment(pg_store)
    sequence = 0

    def command(operation, payload):
        nonlocal sequence
        sequence += 1
        return runtime.mutate_worker(**args, sequence=sequence, operation='domain.metrics.' + operation, payload=payload)['value']

    assert command('active', {'resource': RESOURCE}) is True
    assert command('active', {'resource': RESOURCE}) is False
    assert command('feature', {'feature': 'memory', 'resource': RESOURCE}) is True
    assert command('feature', {'feature': 'memory', 'resource': RESOURCE}) is False
    daily = dict(metric_name=CLIENT_ACTIVE_METRIC, dimensions={}, resource=RESOURCE)
    assert command('daily', daily) is True
    assert command('daily', daily) is False
    assert runtime.read_domain('same', 'metrics.features', {})['value'] == ['memory']
    assert runtime.read_domain('same', 'metrics.first_session', {})['value'] == pg_store.get_session('same')['started_at']
    snapshot = runtime.read_domain('same', 'metrics.snapshot', {})['value']
    assert sum(row['value'] for row in snapshot if row['metric_name'] == CLIENT_ACTIVE_METRIC) == 2
