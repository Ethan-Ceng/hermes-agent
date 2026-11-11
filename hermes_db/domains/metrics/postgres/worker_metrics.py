"""Atomic worker engagement and root membership state on supplied metrics resources."""
import json
from datetime import datetime, UTC
from sqlalchemy import delete, select
from hermes_db.domains.metrics import policy as native
from hermes_cli.observability import shared_metrics_contract as contract
from hermes_db.domains.metrics.postgres import records as metrics, records as repo
from hermes_db.domains.runtime.postgres.operations.worker_domains import ReceiptDomainResource
from hermes_db.tables.metrics import state
from hermes_db.domains.runtime.values import RuntimeStoreError
PREFIX = 'worker.root_profile.v1:'
BATCH_SIZE = 128


def validate_engagement(payload):
    surface, route, resource = payload['surface'], payload['route'], payload['resource']
    if surface is not None and (not isinstance(surface, str) or surface not in contract.ENGAGEMENT_SURFACES):
        raise RuntimeStoreError('invalid_params')
    if route is not None:
        if not isinstance(route, (list, tuple)) or len(route) != 2:
            raise RuntimeStoreError('invalid_params')
        if any(not isinstance(value, str) or value != contract._metric_identifier(value,
                max_length=contract._MODEL_ROUTE_MAX_LENGTHS[key]) for key, value in zip(('provider', 'model'), route)):
            raise RuntimeStoreError('invalid_params')
        route = tuple(route)
    if not contract.client_resource_is_valid(resource) or surface is None and route is None:
        raise RuntimeStoreError('invalid_params')
    return surface, route, resource


def record(conn, scope, *, stamp, resource, surface, route, profile, owner, busy_peak, root_collects):
    from hermes_cli.observability.shared_metrics_engagement import apply as apply_engagement, STATE_KEY
    current = ReceiptDomainResource(conn, scope, writable=True)
    metrics.rollup(conn, current, STATE_KEY, lambda previous: apply_engagement(previous,
        now_ms=stamp, resource=resource, surface=surface, route=route, profile=profile if owner else None,
        owner=owner, busy_peak=busy_peak))
    if profile is not None and not owner and root_collects:
        day = datetime.fromtimestamp(stamp / 1000, UTC).date().isoformat()
        # Only one Profile-membership fact per day; routes and activity are never replayed into root.
        repo.set_state(conn, current, PREFIX + day, native._compact_json({
            'version': 1, 'stamp': stamp, 'profile': profile, 'resource': resource}))

def pending(conn, resource):
    return conn.execute(select(state.c.key, state.c.value).where(repo.scope(state, resource))).all()


def apply_root(conn, resource, update):
    from hermes_cli.observability.shared_metrics_engagement import STATE_KEY
    metrics.rollup(conn, resource, STATE_KEY, update)


def forget(conn, resource, key, value):
    conn.execute(delete(state).where(repo.scope(state, resource), state.c.key == key, state.c.value == value))
