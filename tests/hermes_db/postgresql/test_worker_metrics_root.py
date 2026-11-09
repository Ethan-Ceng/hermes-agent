"""Real pool-one cross-Profile intent replay, withdrawal and UTC-day fencing."""

from datetime import timedelta
from dataclasses import replace
import json
import shutil

import pytest

from hermes_cli.observability import shared_metrics as native, shared_metrics_engagement as engagement
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_db.domains.metrics import open_metrics
from hermes_db.domains.metrics_bound import bound_store
from hermes_db.errors import UnknownCommitError
from hermes_db.operations import worker_metrics_engagement as intents
from hermes_db.repositories import metrics as repo
from tests.hermes_db.postgresql.test_metrics_store import DAY, RESOURCE
from tests.hermes_db.postgresql.test_worker_domain_receipts import assignment

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def rollup(store):
    with open_metrics(store.reference) as (conn, resource):
        raw = repo.get_state(conn, resource, engagement.STATE_KEY)
    return None if raw is None else json.loads(raw)


@pytest.mark.parametrize('edge', ['post_commit_loss', 'late', 'withdraw'])
def test_root_intents_commit_without_source_connection_and_never_count_a_later_day(pg_profiles, monkeypatch, edge):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db

    monkeypatch.setattr(native, '_utc_now', lambda: DAY)
    with pg_profiles('root') as home:
        config = read_user_config_raw(home / 'config.yaml')
        config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
        config['telemetry'] = {'shared_metrics': {'enabled': True, 'send': False}}
        atomic_config_write(home / 'config.yaml', config)
        child = home / 'profiles' / 'satellite'
        child.mkdir(parents=True)
        config['storage']['postgresql']['store_id'] = 'satellite'
        atomic_config_write(child / 'config.yaml', config)
        shutil.copyfile(home / '.env', child / '.env')
        assert engagement._root_home(child) == home
        root = SharedMetricsStore(profile_home=home)
        with open_profile_db(child) as child_db:
            runtime, args = assignment(child_db.sessions)
            runtime.mutate_worker(**args, sequence=1, operation='domain.metrics.engagement',
                payload=dict(surface='cli', route=['openai', 'gpt-4.1'], resource=RESOURCE))
            source = bound_store(child_db.sessions.scope, child_db.sessions._transactions)
            assert len(intents.pending(source)) == 1
            assert rollup(source)['profiles'] == []
            original = intents.apply_root

            def observed(store, observation):
                assert child_db.sessions._transactions.engine.pool.checkedout() == 0
                original(store, observation)
                if edge == 'post_commit_loss':
                    raise UnknownCommitError('root actually committed before source intent deletion')

            if edge == 'late':
                stamp = int((DAY + timedelta(days=1)).timestamp() * 1000)
                root.update_rollup_state(engagement.STATE_KEY, lambda previous: engagement.apply(previous,
                    now_ms=stamp, resource=RESOURCE, profile='already-active-new-day', owner=True))
            elif edge == 'withdraw':
                current = read_user_config_raw(home / 'config.yaml')
                current['telemetry']['shared_metrics']['enabled'] = False
                atomic_config_write(home / 'config.yaml', current)
            with monkeypatch.context() as patch:
                patch.setattr(intents, 'apply_root', observed)
                if edge == 'post_commit_loss':
                    with pytest.raises(UnknownCommitError):
                        intents.drain(source)
                    assert len(intents.pending(source)) == 1
                    assert rollup(root)['profiles'] == [engagement._profile_hash(child)]
                else:
                    intents.drain(source)
            intents.drain(source)
            assert not intents.pending(source)
            current = rollup(root)
            if edge == 'post_commit_loss':
                assert current['profiles'] == [engagement._profile_hash(child)] and current['models'] == {}
            elif edge == 'late':
                assert current['day'] == (DAY + timedelta(days=1)).date().isoformat()
                assert current['profiles'] == ['already-active-new-day']
            else:
                assert current is None


def test_root_keeps_its_own_pg_target_when_satellite_uses_another_owned_schema(pg_profiles, postgres_engine, postgres_test_config):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db
    from hermes_db.integration.transfer.move_values import resource_key
    from hermes_db.schema import upgrade_schema
    from tests.hermes_db.pg_support import isolated_namespace

    with pg_profiles('root') as home, isolated_namespace(postgres_engine, postgres_test_config) as other_schema:
        upgrade_schema(replace(postgres_test_config.settings, schema=other_schema))
        config = read_user_config_raw(home / 'config.yaml')
        config['storage']['postgresql'].update(pool_size=1, max_overflow=0, connection_budget=1)
        config['telemetry'] = {'shared_metrics': {'enabled': True, 'send': False}}
        atomic_config_write(home / 'config.yaml', config)
        root = SharedMetricsStore(profile_home=home)
        child = home / 'profiles' / 'satellite'
        child.mkdir(parents=True)
        config['storage']['postgresql'].update(store_id='satellite', schema=other_schema)
        atomic_config_write(child / 'config.yaml', config)
        shutil.copyfile(home / '.env', child / '.env')
        with open_profile_db(child) as selected:
            db = selected.sessions
            assert resource_key(db._transactions) != root.reference.target
            canonical, scope = assignment(db)
            canonical.mutate_worker(**scope, sequence=1, operation='domain.metrics.engagement',
                payload=dict(surface='cli', route=None, resource=RESOURCE))
            source = bound_store(db.scope, db._transactions)
            assert len(intents.pending(source)) == 1
            intents.drain(source)
            assert not intents.pending(source)
            assert rollup(root)['profiles'] == [engagement._profile_hash(child)]
            assert rollup(source)['profiles'] == []
