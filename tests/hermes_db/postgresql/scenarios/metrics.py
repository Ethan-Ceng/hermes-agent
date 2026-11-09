"""Fresh-process metrics use the selected PG store and reject every SQLite entry."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, UTC

attempts = []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite rejected in actual PG metrics process")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)
from hermes_db.domains.metrics import policy as native
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC

DAY = datetime(2026, 8, 10, tzinfo=UTC)
RESOURCE = dict(hermes_version="test", os_family="windows", architecture="x86_64", install_method="git")
native._utc_now = lambda: DAY + timedelta(hours=12)
role = sys.argv[1]
store = SharedMetricsStore()
if role == "increment":
    sys.stdin.readline()
    for _ in range(20):
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
    store.record_client_active(RESOURCE)
    print("PG_METRICS_INCREMENT_OK")
elif role == "read_package":
    assert store.counter_snapshot()[0]["value"] == 41
    paths = store.create_and_export_package()
    assert len(paths) == 1
    assert json.loads(paths[0].read_text(encoding="utf-8"))["metrics"][0]["value"] == 41
    print("PG_METRICS_RESTART_PACKAGE_OK")
elif role == "export_recovery":
    paths = store.create_and_export_package()
    assert len(paths) == 1
    assert json.loads(paths[0].read_text(encoding="utf-8"))["metrics"][0]["value"] == 1
    assert store.create_and_export_package() == []
    print("PG_METRICS_EXPORT_RECOVERY_OK")
else:
    raise AssertionError("unknown metrics probe role")
assert not attempts
