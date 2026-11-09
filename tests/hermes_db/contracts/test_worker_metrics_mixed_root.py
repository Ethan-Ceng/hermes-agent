"""Explicitly mixed Profiles: a PG satellite and its independently selected SQLite root."""

from dataclasses import replace
import json
import sys

import pytest

from hermes_cli.observability import shared_metrics_engagement as engagement
from hermes_db.domains.metrics.bound import bound_store
from hermes_db.integration.worker_metrics import drain, pending
from tests.hermes_db.postgresql.test_metrics_store import RESOURCE
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_pg_satellite_reconciles_sqlite_root_under_each_profiles_own_backend(postgres_test_config, postgres_schema, tmp_path):
    from hermes_cli.config import atomic_config_write
    from hermes_cli.db_setup import _owning_profile, open_profile_db
    from hermes_constants import get_hermes_home
    from hermes_db.schema import upgrade_schema

    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(settings)
    root = tmp_path / 'root'
    child = root / 'profiles' / 'satellite'
    child.mkdir(parents=True)
    telemetry = {'shared_metrics': {'enabled': True, 'send': False}}
    atomic_config_write(root / 'config.yaml', {'storage': {'backend': 'sqlite'}, 'telemetry': telemetry})
    atomic_config_write(child / 'config.yaml', {'storage': {'backend': 'postgresql', 'postgresql': {
        'schema': settings.schema, 'store_id': 'satellite', 'pool_size': 1, 'max_overflow': 0, 'connection_budget': 1}}, 'telemetry': telemetry})
    (child / '.env').write_text('HERMES_POSTGRES_DSN=' + json.dumps(settings.dsn) + '\n', encoding='utf-8')
    connections, enabled = [], [True]

    def audit(event, args):
        if enabled[0] and event == 'sqlite3.connect':
            # Every SQLite connection belongs to the explicitly SQLite Profile, including reads/constructors.
            assert get_hermes_home().resolve() == root
            connections.append(args[0])

    sys.addaudithook(audit)
    try:
        with _owning_profile(child), open_profile_db(child) as owner:
            canonical, scope = assignment(owner.sessions)
            canonical.mutate_worker(**scope, sequence=1, operation='domain.metrics.engagement',
                payload=dict(surface='cli', route=['openai', 'gpt-4.1'], resource=RESOURCE))
            source = bound_store(owner.sessions.scope, owner.sessions._transactions)
            assert len(pending(source)) == 1
            drain(source)
            assert get_hermes_home().resolve() == child
            assert not pending(source)
        with _owning_profile(root):
            store = engagement._root_store(root)
            with store._connection() as conn:
                row = conn.execute('SELECT value FROM telemetry_state WHERE key=?', (engagement.STATE_KEY,)).fetchone()
            assert json.loads(row['value'])['profiles'] == [engagement._profile_hash(child)]
        assert connections
        assert not (child / 'telemetry/shared_metrics/metrics.sqlite3').exists()
    finally:
        enabled[0] = False
