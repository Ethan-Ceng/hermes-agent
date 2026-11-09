"""Closed metric effects on the worker receipt connection; no client clocks or state keys."""

from functools import partial
import json

from sqlalchemy import func, select

from hermes_db.domains.metrics import policy as native
from hermes_db.domains.metrics.bound import bound_store
from hermes_db.domains.runtime.postgres.operations.worker_domains import ReceiptDomainResource, fields
from hermes_db.domains.metrics.postgres import records as repo
from hermes_db.tables.conversations import sessions
from hermes_db.domains.runtime.values import RuntimeStoreError

READS = frozenset('metrics.' + name for name in ('milestones', 'features', 'snapshot_due', 'first_session', 'snapshot'))
FIELDS = {
    'counter': {'metric_name', 'dimensions', 'resource', 'amount'},
    'daily': {'metric_name', 'dimensions', 'resource'}, 'active': {'resource'},
    'install_snapshot': {'dimensions', 'resource'}, 'milestone': {'milestone', 'resource'},
    'feature': {'feature', 'resource'}, 'engagement': {'surface', 'route', 'resource'},
    'consent': set(), 'flush': set(),
}




def first_session(conn, scope):
    value = conn.scalar(select(func.min(sessions.c.started_at)).where(sessions.c.store_id == scope.require_store_id()))
    return native._utc_now().timestamp() if value is None else float(value)


def invoke(conn, scope, session_id, payload, *, operation, policy, record_engagement):
    fields(payload, FIELDS[operation])
    if len(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()) > 16384:
        raise RuntimeStoreError('invalid_params')
    resource = ReceiptDomainResource(conn, scope, writable=True)
    store = bound_store(scope, resource)
    # Session receipts and ordinary metrics use different fences: retain the ordinary metrics lock too.
    repo.lock_store(conn, resource)
    callbacks = {
        'counter': lambda: store.record_counter(**payload),
        'daily': lambda: store.record_counter_once_per_day(**payload),
        'active': lambda: store.record_client_active(**payload),
        'install_snapshot': lambda: store.record_install_snapshot(**payload),
        'milestone': lambda: milestone(conn, scope, store, payload),
        'feature': lambda: feature(conn, scope, store, payload),
        'consent': lambda: store.reconcile_send_consent(policy),
        'engagement': lambda: record_engagement(conn, scope, store, payload, root_collects=policy),
        'flush': lambda: None,
    }
    return {'value': callbacks[operation]()}


def milestone(conn, scope, store, payload):
    from hermes_cli.observability.shared_metrics_fields import install_age_bucket
    age = install_age_bucket(native._utc_now().timestamp() - first_session(conn, scope))
    return store.record_milestone(payload['milestone'], age, payload['resource'])


def feature(conn, scope, store, payload):
    from hermes_cli.observability.shared_metrics_contract import _bucket
    from hermes_cli.observability.shared_metrics_signals import _DAYS_SINCE_INSTALL_THRESHOLDS
    age = max(0, native._utc_now().timestamp() - first_session(conn, scope))
    return store.record_feature_adoption(payload['feature'], _bucket(age, _DAYS_SINCE_INSTALL_THRESHOLDS, 'gte_90d'), payload['resource'])




def handlers(policy=None, *, record_engagement):
    return {'domain.metrics.' + name: partial(invoke, operation=name, policy=policy, record_engagement=record_engagement) for name in FIELDS}


def read(conn, scope, session_id, name, arguments):
    fields(arguments, set())
    store = bound_store(scope, ReceiptDomainResource(conn, scope))
    callbacks = {
        'metrics.milestones': lambda: sorted(store.recorded_milestones()),
        'metrics.features': lambda: sorted(store.recorded_features()),
        'metrics.snapshot_due': store.install_snapshot_due,
        'metrics.first_session': lambda: first_session(conn, scope),
        'metrics.snapshot': store.counter_snapshot,
    }
    if name not in callbacks:
        raise RuntimeStoreError('invalid_params')
    return {'value': callbacks[name]()}
