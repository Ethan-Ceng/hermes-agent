"""Compute-only public metrics facade; all durable effects belong to the adopted owner."""

from agent.runtime_domain_store import worker_resource
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_db.errors import StorageConfigurationError


class WorkerMetricsStore(SharedMetricsStore):
    backend = 'postgresql'
    owner_managed = True

    def __init__(self, database_path=None, outbox_directory=None, *, profile_home=None):
        self.reference = worker_resource('metrics', profile_home=profile_home)
        self.profile_home = self.reference.scope.profile_home
        self.database_path = None
        self.outbox_directory = None

    def _command(self, name, **payload):
        return self.reference.command('metrics.' + name, payload)

    def _query(self, name):
        return self.reference.query('metrics.' + name, {})

    def _connection(self, **kwargs):
        raise StorageConfigurationError('Worker metrics expose owner operations, not a connection')

    def _write(self, **kwargs):
        raise StorageConfigurationError('Worker metrics expose owner operations, not a transaction')

    def update_rollup_state(self, state_key, update):
        raise StorageConfigurationError('Worker metrics require a named engagement observation, not a callback')

    def record_counter(self, metric_name, dimensions, resource, amount=1):
        return self._command('counter', metric_name=metric_name, dimensions=dimensions, resource=resource, amount=amount)

    def record_counter_once_per_day(self, metric_name, dimensions, resource):
        return self._command('daily', metric_name=metric_name, dimensions=dimensions, resource=resource)

    def record_client_active(self, resource):
        return self._command('active', resource=resource)

    def record_install_snapshot(self, dimensions, resource):
        return self._command('install_snapshot', dimensions=dimensions, resource=resource)

    def record_milestone(self, milestone, install_age_bucket, resource):
        return self._command('milestone', milestone=milestone, resource=resource)

    def record_feature_adoption(self, feature, days_bucket, resource):
        return self._command('feature', feature=feature, resource=resource)

    def record_engagement(self, resource, *, surface, route):
        return self._command('engagement', resource=resource, surface=surface, route=route)

    def recorded_milestones(self):
        return frozenset(self._query('milestones'))

    def recorded_features(self):
        return frozenset(self._query('features'))

    def install_snapshot_due(self):
        return self._query('snapshot_due')

    def counter_snapshot(self):
        return self._query('snapshot')

    def reconcile_send_consent(self, send_enabled, *, now=None):
        # Frozen agent defaults do not authorize or revoke the Profile owner's send window.
        return self._command('consent')

    def create_and_export_package_if_due(self):
        self._command('flush')
        return []

    def drain_deferred(self, **kwargs):
        self.reference.store.flush_token_counts()
