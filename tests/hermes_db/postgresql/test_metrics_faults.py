"""Durable metric watermarks, exact claims and recovery across failure windows."""

from datetime import timedelta
import json
import pytest
from hermes_db.domains.metrics import policy as native
from hermes_cli.observability import shared_metrics_postgres as metric_export
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender
from hermes_cli.observability.shared_metrics_postgres import open_metrics
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.metrics.postgres import outbox as metric_packages
from hermes_db.domains.metrics.postgres import records as repo
from hermes_db.tables.metrics import packages
from sqlalchemy import select
from tests.hermes_db.postgresql.test_metrics_store import DAY, RESOURCE

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def seeded(monkeypatch):
    monkeypatch.setattr(native, "_utc_now", lambda: DAY + timedelta(hours=12))
    store = SharedMetricsStore()
    store.reconcile_send_consent(True, now=DAY - timedelta(days=1))
    store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
    store.create_and_export_package()
    store.reconcile_send_consent(True, now=DAY + timedelta(days=1))
    return store


def test_export_failure_preserves_committed_package_and_exact_delta(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        monkeypatch.setattr(native, "_utc_now", lambda: DAY)
        store = SharedMetricsStore()
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        original = metric_export.atomic_json_write
        def refuse(*args, **kwargs):
            raise OSError("injected export refusal")
        monkeypatch.setattr(metric_export, "atomic_json_write", refuse)
        with pytest.raises(OSError, match="injected export"):
            store.create_and_export_package()
        assert store.counter_snapshot()[0]["packaged_value"] == 1
        monkeypatch.setattr(metric_export, "atomic_json_write", original)
        paths = SharedMetricsStore().create_and_export_package()
        assert len(paths) == 1
        assert json.loads(paths[0].read_text(encoding="utf-8"))["metrics"][0]["value"] == 1
        assert SharedMetricsStore().create_and_export_package() == []


def test_package_failure_rolls_back_watermark_with_insert(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        monkeypatch.setattr(native, "_utc_now", lambda: DAY)
        store = SharedMetricsStore()
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        original = metric_packages.mark_packaged
        def fail(*args, **kwargs):
            raise RuntimeError("injected package transaction refusal")
        monkeypatch.setattr(metric_packages, "mark_packaged", fail)
        with pytest.raises(RuntimeError, match="transaction refusal"):
            store.create_and_export_package()
        assert store.counter_snapshot()[0]["packaged_value"] == 0
        with open_metrics(store.reference) as (conn, resource):
            assert conn.scalar(select(packages.c.package_id).where(repo.scope(packages, resource))) is None
        monkeypatch.setattr(metric_packages, "mark_packaged", original)
        assert len(store.create_and_export_package()) == 1


def test_unknown_package_commit_retry_does_not_double_package(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        monkeypatch.setattr(native, "_utc_now", lambda: DAY)
        store = SharedMetricsStore()
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        def lost_ack():
            store._create_package()
            raise UnknownCommitError("injected post-COMMIT confirmation loss")
        with pytest.raises(UnknownCommitError):
            lost_ack()
        assert len(SharedMetricsStore().create_and_export_package()) == 1
        assert SharedMetricsStore().create_and_export_package() == []
        assert store.counter_snapshot()[0]["packaged_value"] == 1


def test_claim_expiry_reclaim_rejects_late_settlement_and_identity_rotation(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        store = seeded(monkeypatch)
        first = SharedMetricsSender(store, "https://telemetry.test", now=lambda: DAY + timedelta(days=1))
        old = first._claim_next(DAY + timedelta(days=1), set())
        assert old is not None
        with open_metrics(store.reference, write=True) as (conn, resource):
            repo.set_state(conn, resource, "install_id", "new-install-id")
        later = DAY + timedelta(days=1, minutes=6)
        second = SharedMetricsSender(SharedMetricsStore(), "https://telemetry.test", now=lambda: later)
        current = second._claim_next(later, set())
        assert current["claim_token"] != old["claim_token"]
        assert current["derived"] == old["derived"]
        assert first._body(old["payload_json"], old["derived"]) == second._body(current["payload_json"], current["derived"])
        assert not first._renew_claim(old["package_id"], old["claim_token"])
        first._mark(old["package_id"], token=old["claim_token"], send_state="sent")
        with open_metrics(store.reference) as (conn, resource):
            row = conn.execute(select(packages).where(repo.scope(packages, resource))).mappings().one()
            assert row["send_state"] == "pending" and row["claim_token"] == current["claim_token"]
        second._mark(current["package_id"], token=current["claim_token"], send_state="sent")
        assert second._claim_next(later, set()) is None
