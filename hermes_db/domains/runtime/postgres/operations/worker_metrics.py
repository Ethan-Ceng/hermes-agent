"""Closed metric effects on the worker receipt connection; no client clocks or state keys."""

from functools import partial
import json

from sqlalchemy import func, select

from hermes_cli.observability import shared_metrics as native
from hermes_db.domains.metrics.bound import bound_store
from hermes_db.domains.runtime.postgres.operations.worker_domains import ReceiptDomainResource, fields
from hermes_db.domains.metrics.postgres.queries import metrics as repo
from hermes_db.tables.conversations import sessions
from hermes_state_runtime import RuntimeStoreError

READS = frozenset('metrics.' + name for name in ('milestones', 'features', 'snapshot_due', 'first_session', 'snapshot'))
FIELDS = {
    'counter': {'metric_name', 'dimensions', 'resource', 'amount'},
    'daily': {'metric_name', 'dimensions', 'resource'}, 'active': {'resource'},
    'install_snapshot': {'dimensions', 'resource'}, 'milestone': {'milestone', 'resource'},
    'feature': {'feature', 'resource'}, 'engagement': {'surface', 'route', 'resource'},
    'consent': set(), 'flush': set(),
}


def prepare_policy(home, operation):
    if operation not in {'domain.metrics.consent', 'domain.metrics.engagement'}:
        return None
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.observability import shared_metrics_engagement as engagement
    from hermes_cli.observability.relay_shared_metrics import _resolved_send_config
    if operation == 'domain.metrics.consent':
        with _owning_profile(home):
            return _resolved_send_config().send
    root = engagement._root_home(home)
    return root != home and engagement._collects(root)


def first_session(conn, scope):
    value = conn.scalar(select(func.min(sessions.c.started_at)).where(sessions.c.store_id == scope.require_store_id()))
    return native._utc_now().timestamp() if value is None else float(value)


def invoke(conn, scope, session_id, payload, *, operation, policy):
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
        'engagement': lambda: observe_engagement(conn, scope, store, payload, policy),
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


def observe_engagement(conn, scope, store, payload, root_collects):
    from hermes_db.domains.runtime.postgres.operations.worker_metrics_engagement import record
    return record(conn, scope, store, payload, root_collects=root_collects)


def handlers(policy=None):
    return {'domain.metrics.' + name: partial(invoke, operation=name, policy=policy) for name in FIELDS}


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
