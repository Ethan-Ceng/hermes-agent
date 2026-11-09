"""PG consent windows must preserve refused eras and fail closed under bad clocks."""

import pytest
from hermes_cli.observability import shared_metrics as native
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender
from tests.hermes_db.postgresql.test_metrics_store import DAY, RESOURCE
from datetime import timedelta

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def package(store, monkeypatch, day):
    monkeypatch.setattr(native, "_utc_now", lambda: day + timedelta(hours=12))
    store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
    result = store._create_package()
    store._export_pending_packages()
    return result["package_id"]


def claimed(store, when):
    sender = SharedMetricsSender(store, "https://telemetry.test", now=lambda: when)
    found, seen = [], set()
    while (row := sender._claim_next(when, seen)) is not None:
        seen.add(row["package_id"])
        found.append(row["package_id"])
    return set(found)


def test_consent_on_off_on_never_releases_refused_middle(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        store = SharedMetricsStore()
        store.reconcile_send_consent(True, now=DAY)
        first = package(store, monkeypatch, DAY)
        store.reconcile_send_consent(True, now=DAY + timedelta(days=1))
        store.reconcile_send_consent(False, now=DAY + timedelta(days=1))
        refused = package(store, monkeypatch, DAY + timedelta(days=1))
        store.reconcile_send_consent(True, now=DAY + timedelta(days=2))
        last = package(store, monkeypatch, DAY + timedelta(days=2))
        store.reconcile_send_consent(True, now=DAY + timedelta(days=3))
        eligible = claimed(SharedMetricsStore(), DAY + timedelta(days=3))
        assert eligible == {first, last}
        assert refused not in eligible
    with pg_profiles("two"):
        other = SharedMetricsStore()
        package(other, monkeypatch, DAY)
        assert claimed(other, DAY + timedelta(days=3)) == set()


def test_rollback_reopen_is_clamped_above_committed_data(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        store = SharedMetricsStore()
        pid = package(store, monkeypatch, DAY)
        store.reconcile_send_consent(True, now=DAY - timedelta(days=3))
        store.reconcile_send_consent(True, now=DAY + timedelta(days=1))
        assert pid not in claimed(store, DAY + timedelta(days=1))


def test_forward_poison_then_revoke_closes_at_raw_revoke_time(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        store = SharedMetricsStore()
        store.reconcile_send_consent(True, now=DAY)
        store.reconcile_send_consent(True, now=DAY + timedelta(days=5000))
        store.reconcile_send_consent(False, now=DAY + timedelta(days=1))
        first = package(store, monkeypatch, DAY)
        later = package(store, monkeypatch, DAY + timedelta(days=2))
        eligible = claimed(store, DAY + timedelta(days=3))
        assert first in eligible and later not in eligible


def test_fully_disabled_lifecycle_closes_each_profile_without_sqlite_file(pg_profiles, monkeypatch):
    from hermes_cli.observability import relay_shared_metrics as relay
    from hermes_db.domains.metrics.api import open_metrics
    from hermes_db.domains.metrics.postgres.outbox import consented_day
    monkeypatch.setattr(relay, "_consent_reconcile_done", set())
    monkeypatch.setattr(relay, "_raw_config", lambda: {"telemetry": {"shared_metrics": {"enabled": False, "send": False}}})
    for name in ("one", "two"):
        with pg_profiles(name):
            store = SharedMetricsStore()
            store.reconcile_send_consent(True, now=DAY)
            relay._reconcile_send_consent_once()
            with open_metrics(store.reference) as (conn, resource):
                assert not consented_day(conn, resource, native._isoformat(DAY + timedelta(days=1)))
