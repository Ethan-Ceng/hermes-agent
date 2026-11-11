"""Actual SQLite metrics aggregation, consent, packaging and sending without PG extras."""

import subprocess
import sys


def test_metrics_sqlite_standalone_without_postgresql_drivers(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    code = r'''
import importlib.abc, sys
from datetime import datetime, timedelta, UTC
class BlockDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy','psycopg','alembic'}:
            raise ImportError('PG dependency blocked by standalone SQLite contract')
sys.meta_path.insert(0, BlockDrivers())
from hermes_cli.observability import shared_metrics as native
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender
from types import SimpleNamespace
day = datetime(2026,8,10,tzinfo=UTC)
native._utc_now = lambda:day
store = SharedMetricsStore.create()
store.reconcile_send_consent(True, now=day-timedelta(days=1))
store.record_counter(CLIENT_ACTIVE_METRIC, {}, dict(hermes_version='test',os_family='windows',architecture='x86_64',install_method='git'))
assert len(store.create_and_export_package()) == 1
store.reconcile_send_consent(True, now=day+timedelta(days=1))
sent = []
def post(endpoint, data, **kwargs):
    sent.append(data)
    return SimpleNamespace(status=202,retry_after=None,body='')
sender = SharedMetricsSender(SharedMetricsStore(), 'https://telemetry.test', post=post, now=lambda:day+timedelta(days=1))
assert sender.send_pending().sent == 1 and len(sent) == 1
assert sender.send_pending().sent == 0
print('SQLITE_METRICS_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(tmp_path), HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_METRICS_STANDALONE_OK" in result.stdout
