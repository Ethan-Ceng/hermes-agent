"""Owner-clock engagement and bounded, replayable cross-Profile membership intents."""

import json
from datetime import datetime, UTC


from hermes_db.domains.metrics import policy as native
from hermes_cli.observability import shared_metrics_contract as contract
from hermes_cli.observability import shared_metrics_engagement as engagement
from hermes_db.core.values import decode_text

from hermes_db.domains.metrics.postgres.worker_metrics import PREFIX, BATCH_SIZE


def record(conn, scope, store, payload, *, root_collects):
    from hermes_db.domains.metrics.postgres import worker_metrics as business
    surface, route, resource = business.validate_engagement(payload)
    home = scope.profile_home
    owner = engagement._root_home(home) == home
    profile = engagement._profile_hash(home) if surface is not None else None
    stamp = int(native._utc_now().timestamp() * 1000)
    from hermes_cli.observability.shared_metrics_busy import day_peak
    return business.record(conn, scope, stamp=stamp, resource=resource, surface=surface, route=route,
                           profile=profile, owner=owner, busy_peak=lambda day: day_peak(home, day), root_collects=root_collects)


def pending(store):
    from hermes_cli.observability.shared_metrics_postgres import open_metrics
    from hermes_db.domains.metrics.postgres import worker_metrics as business
    with open_metrics(store.reference) as (conn, resource):
        rows = business.pending(conn, resource)
    return [(key, value) for key, value in rows if decode_text(key).startswith(PREFIX)][:BATCH_SIZE]


def apply_root(store, observation):
    def update(previous):
        day = datetime.fromtimestamp(observation['stamp'] / 1000, UTC).date().isoformat()
        if isinstance(previous, dict) and previous.get('day', '') > day:
            return previous, []
        return engagement.apply(previous, now_ms=observation['stamp'], resource=observation['resource'],
            profile=observation['profile'], owner=True)

    from hermes_db.domains.metrics.postgres import worker_metrics as business
    if getattr(store, 'backend', 'sqlite') == 'postgresql':
        from hermes_cli.observability.shared_metrics_postgres import open_metrics
        with open_metrics(store.reference, write=True) as (conn, resource):
            business.apply_root(conn, resource, update)
    else:
        # The root must really commit before the source intent is deleted; don't use SQLite's deferred queue.
        with store._write(busy_timeout_ms=native._SCHEMA_BUSY_TIMEOUT_MS) as conn:
            store._update_rollup_state(conn, engagement.STATE_KEY, update)


def drain(store):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.observability.shared_metrics_postgres import open_metrics
    root = engagement._root_home(store.profile_home)
    for key, value in pending(store):
        observation = json.loads(decode_text(value))
        if engagement._collects(root):
            with _owning_profile(root):
                apply_root(engagement._root_store(root), observation)
        # root has committed (or collection was withdrawn); this CAS cannot delete a newer observation.
        with open_metrics(store.reference, write=True) as (conn, resource):
            from hermes_db.domains.metrics.postgres.worker_metrics import forget
            forget(conn, resource, key, value)
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
