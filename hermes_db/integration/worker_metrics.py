"""Owner-clock engagement and bounded, replayable cross-Profile membership intents."""

import json
from datetime import datetime, UTC

from sqlalchemy import delete, select

from hermes_db.domains.metrics import policy as native
from hermes_cli.observability import shared_metrics_contract as contract
from hermes_cli.observability import shared_metrics_engagement as engagement
from hermes_db.domains.metrics.postgres import records as metrics
from hermes_db.domains.runtime.postgres.operations.worker_domains import ReceiptDomainResource
from hermes_db.domains.metrics.postgres import records as repo
from hermes_db.tables.metrics import state
from hermes_db.core.values import decode_text
from hermes_db.domains.runtime.values import RuntimeStoreError

PREFIX = 'worker.root_profile.v1:'
BATCH_SIZE = 128


def record(conn, scope, store, payload, *, root_collects):
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
    home = scope.profile_home
    owner = engagement._root_home(home) == home
    profile = engagement._profile_hash(home) if surface is not None else None
    stamp = int(native._utc_now().timestamp() * 1000)
    from hermes_cli.observability.shared_metrics_busy import day_peak
    current = ReceiptDomainResource(conn, scope, writable=True)
    metrics.rollup(conn, current, engagement.STATE_KEY, lambda previous: engagement.apply(previous,
        now_ms=stamp, resource=resource, surface=surface, route=route, profile=profile if owner else None,
        owner=owner, busy_peak=lambda day: day_peak(home, day)))
    if profile is not None and not owner and root_collects:
        day = datetime.fromtimestamp(stamp / 1000, UTC).date().isoformat()
        # Only one Profile-membership fact per day; routes and activity are never replayed into root.
        repo.set_state(conn, current, PREFIX + day, native._compact_json({
            'version': 1, 'stamp': stamp, 'profile': profile, 'resource': resource}))


def pending(store):
    from hermes_db.domains.metrics.api import open_metrics
    with open_metrics(store.reference) as (conn, resource):
        rows = conn.execute(select(state.c.key, state.c.value).where(repo.scope(state, resource))).all()
    return [(key, value) for key, value in rows if decode_text(key).startswith(PREFIX)][:BATCH_SIZE]


def apply_root(store, observation):
    def update(previous):
        day = datetime.fromtimestamp(observation['stamp'] / 1000, UTC).date().isoformat()
        if isinstance(previous, dict) and previous.get('day', '') > day:
            return previous, []
        return engagement.apply(previous, now_ms=observation['stamp'], resource=observation['resource'],
            profile=observation['profile'], owner=True)

    if getattr(store, 'backend', 'sqlite') == 'postgresql':
        from hermes_db.domains.metrics.api import open_metrics
        with open_metrics(store.reference, write=True) as (conn, resource):
            metrics.rollup(conn, resource, engagement.STATE_KEY, update)
    else:
        # The root must really commit before the source intent is deleted; don't use SQLite's deferred queue.
        with store._write(busy_timeout_ms=native._SCHEMA_BUSY_TIMEOUT_MS) as conn:
            store._update_rollup_state(conn, engagement.STATE_KEY, update)


def drain(store):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.domains.metrics.api import open_metrics
    root = engagement._root_home(store.profile_home)
    for key, value in pending(store):
        observation = json.loads(decode_text(value))
        if engagement._collects(root):
            with _owning_profile(root):
                apply_root(engagement._root_store(root), observation)
        # root has committed (or collection was withdrawn); this CAS cannot delete a newer observation.
        with open_metrics(store.reference, write=True) as (conn, resource):
            conn.execute(delete(state).where(repo.scope(state, resource), state.c.key == key, state.c.value == value))
    if pending(store):
        from hermes_db.errors import StorageNotReadyError
        # A bounded pass is not a completed flush. The original worker journal must retain its ACK.
        raise StorageNotReadyError('Metrics membership observations remain; replay the pending flush receipt')

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
