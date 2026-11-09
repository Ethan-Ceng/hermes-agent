"""Selected PG metrics derive rollup ownership from Profile identity, including on reopen."""

import json

import pytest
from sqlalchemy import select

from hermes_cli.observability import shared_metrics_engagement as engagement
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_db.tables.metrics import state
from hermes_db.core.values import decode_text, encode_text
from tests.hermes_db.postgresql.test_metrics_store import RESOURCE

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_pg_rollup_uses_explicit_profile_identity_and_persists_without_sqlite_path(pg_profiles):
    from hermes_cli.db_setup import open_profile_db

    with pg_profiles('one') as home:
        store = SharedMetricsStore(profile_home=home)
        assert store.database_path is None
        engagement.record(store, RESOURCE, surface='cli', route=('openai', 'gpt-4.1'))
        with open_profile_db(home) as reopened, reopened.sessions._transactions.read() as conn:
            raw = conn.scalar(select(state.c.value).where(state.c.store_id == 'one', state.c.key == encode_text(engagement.STATE_KEY)))
        rollup = json.loads(decode_text(raw))
        assert sum(rollup['models'].values()) == 1
        assert 'cli' in rollup['surfaces']
    with pg_profiles('two') as peer, open_profile_db(peer) as other, other.sessions._transactions.read() as conn:
        assert not conn.execute(select(state).where(state.c.store_id == 'two', state.c.key == encode_text(engagement.STATE_KEY))).first()
