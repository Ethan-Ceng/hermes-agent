"""Actual selected metrics backend, scoped durable deltas and consent-gated sends."""

import json
from datetime import datetime, timedelta, UTC

import pytest

from hermes_cli.observability import shared_metrics as native
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender
from tests.hermes_cli.test_shared_metrics_sender import FakeTransport

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]
RESOURCE = dict(hermes_version="版本\x00🙂", os_family="windows", architecture="x86_64", install_method="git")
DAY = datetime(2026, 8, 10, tzinfo=UTC)


def test_metrics_real_deltas_exports_reopen_and_profile_isolation(pg_profiles, monkeypatch):
    monkeypatch.setattr(native, "_utc_now", lambda: DAY + timedelta(hours=12))
    with pg_profiles("one"):
        store = SharedMetricsStore()
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        assert store.record_client_active(RESOURCE)
        assert not SharedMetricsStore().record_client_active(RESOURCE)
        paths = store.create_and_export_package()
        assert len(paths) == 1
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        assert payload["resource"] == RESOURCE
        assert payload["metrics"][0]["value"] == 2
        assert SharedMetricsStore().create_and_export_package() == []
        assert SharedMetricsStore().counter_snapshot()[0]["packaged_value"] == 2
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        second = json.loads(store.create_and_export_package()[0].read_text(encoding="utf-8"))
        assert second["install_id"] == payload["install_id"]
        assert second["metrics"][0]["value"] == 1
    with pg_profiles("two"):
        assert SharedMetricsStore().counter_snapshot() == []


def test_metrics_sender_persists_consent_and_reopens_outbox(pg_profiles, monkeypatch):
    monkeypatch.setattr(native, "_utc_now", lambda: DAY + timedelta(hours=12))
    with pg_profiles("one"):
        store = SharedMetricsStore()
        store.reconcile_send_consent(True, now=DAY - timedelta(days=1))
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        paths = store.create_and_export_package()
        transport = FakeTransport()
        sender = SharedMetricsSender(store, "https://telemetry.test", post=transport, now=lambda: DAY + timedelta(hours=13))
        assert sender.send_pending().sent == 0
        store.reconcile_send_consent(True, now=DAY + timedelta(days=1))
        reopened = SharedMetricsSender(SharedMetricsStore(), "https://telemetry.test", post=transport, now=lambda: DAY + timedelta(days=1))
        assert reopened.send_pending().sent == 1
        assert reopened.send_pending().sent == 0
        assert len(transport.calls) == 1
        assert paths[0].exists()


def test_feature_latch_and_interval_clock_correction_survive_reopen(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        monkeypatch.setattr(native, "_utc_now", lambda: DAY)
        store = SharedMetricsStore()
        assert store.record_feature_adoption("memory", "same_day", RESOURCE)
        assert SharedMetricsStore().recorded_features() == frozenset({"memory"})
        assert not SharedMetricsStore().record_feature_adoption("memory", "1d_to_7d", RESOURCE)
        assert store.record_client_active(RESOURCE)
        monkeypatch.setattr(native, "_utc_now", lambda: DAY - timedelta(hours=1))
        assert not SharedMetricsStore().record_client_active(RESOURCE)
        monkeypatch.setattr(native, "_utc_now", lambda: DAY + timedelta(hours=23))
        assert SharedMetricsStore().record_client_active(RESOURCE)


def test_retention_keeps_unexported_data_and_exports_without_borrowed_connections(pg_profiles, monkeypatch):
    from hermes_db.domains.metrics.api import open_metrics
    from hermes_db.domains.metrics.postgres.outbox import pending_exports
    with pg_profiles("one"):
        store = SharedMetricsStore()
        with open_metrics(store.reference) as (_conn, resource):
            pool = resource._transactions.engine.pool
        original = native.atomic_json_write
        def write(*args, **kwargs):
            borrowed = pool.checkedout()
            assert borrowed == 0
            return original(*args, **kwargs)
        monkeypatch.setattr(native, "atomic_json_write", write)
        monkeypatch.setattr(native, "_utc_now", lambda: DAY - timedelta(days=31))
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        old_file = store.create_and_export_package()[0]
        monkeypatch.setattr(native, "_utc_now", lambda: DAY - timedelta(days=32))
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        waiting = store._create_package()
        monkeypatch.setattr(native, "_utc_now", lambda: DAY)
        store._prune_expired_history()
        assert not old_file.exists()
        rows = store.counter_snapshot()
        assert len(rows) == 1 and rows[0]["period_start"] == (DAY - timedelta(days=32)).date().isoformat()
        with open_metrics(store.reference) as (conn, resource):
            assert [row["package_id"] for row in pending_exports(conn, resource)] == [waiting["package_id"]]
