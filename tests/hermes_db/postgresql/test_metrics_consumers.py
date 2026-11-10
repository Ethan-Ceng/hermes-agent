"""Actual off-turn metrics consumers, including opt-out and selected session age."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import pytest
from hermes_db.domains.metrics import policy as native
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from hermes_db.domains.metrics.api import open_metrics
from hermes_db.domains.metrics.postgres import records as repo
from tests.hermes_db.postgresql.test_metrics_store import DAY, RESOURCE

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_captured_profile_thread_under_another_ambient_profile(pg_profiles, monkeypatch):
    monkeypatch.setattr(native, "_utc_now", lambda: DAY)
    with pg_profiles("one") as home:
        store = SharedMetricsStore(profile_home=home)
    with pg_profiles("two"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(store.record_counter, CLIENT_ACTIVE_METRIC, {}, RESOURCE).result(timeout=20)
        assert SharedMetricsStore().counter_snapshot() == []
        assert store.counter_snapshot()[0]["value"] == 1


def test_rollup_and_daily_latches_persist_exactly_once(pg_profiles, monkeypatch):
    monkeypatch.setattr(native, "_utc_now", lambda: DAY)
    def close(previous):
        return {"done": True, "opaque": "零\x00🙂"}, [] if previous else [(CLIENT_ACTIVE_METRIC, {}, RESOURCE, DAY.date().isoformat())]
    with pg_profiles("one"):
        store = SharedMetricsStore()
        store.update_rollup_state("rollup:\x00🙂", close)
        SharedMetricsStore().update_rollup_state("rollup:\x00🙂", close)
        assert store.record_counter_once_per_day(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        assert not SharedMetricsStore().record_counter_once_per_day(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        assert store.counter_snapshot()[0]["value"] == 2
        with open_metrics(store.reference) as (conn, resource):
            assert json.loads(repo.get_state(conn, resource, "rollup:\x00🙂")) == {"done": True, "opaque": "零\x00🙂"}


def test_install_day_and_setup_opt_out_use_selected_backend(pg_profiles, monkeypatch):
    from hermes_cli import setup
    from hermes_cli.observability import shared_metrics_install_run as installs
    monkeypatch.setattr(native, "_utc_now", lambda: DAY)
    with pg_profiles("one") as home:
        monkeypatch.setattr("hermes_cli.config.read_raw_config_readonly", lambda: {"telemetry": {"shared_metrics": {"enabled": True, "send": True}}})
        store = SharedMetricsStore()
        store.reconcile_send_consent(True, now=DAY - timedelta(days=1))
        assert installs.consented_day(home)
        setup._record_send_consent_change(enabled=False)
        assert not installs.consented_day(home)


def test_install_age_queries_real_scoped_sessions_and_ignores_old_sqlite(pg_profiles):
    from hermes_cli.observability.shared_metrics_snapshot import _first_session_started_at
    from hermes_cli.db_sessions import open_session_store
    with pg_profiles("one") as home:
        (home / "state.db").write_bytes(b"old SQLite data must remain unopened")
        db = open_session_store(home / "state.db")
        try:
            db.create_session("metric-session", "cli")
            started = db.get_session("metric-session")["started_at"]
            assert _first_session_started_at(home) == started
            assert (home / "state.db").read_bytes() == b"old SQLite data must remain unopened"
        finally:
            db.close()
    with pg_profiles("two") as home:
        assert _first_session_started_at(home) != started
