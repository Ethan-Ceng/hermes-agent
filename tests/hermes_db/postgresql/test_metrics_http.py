"""Actual loopback HTTP plus PG claims, including accepted POST with a lost receipt."""

from datetime import timedelta
from http.server import HTTPServer
from threading import Thread
import pytest
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender
from hermes_db.domains.metrics.api import open_metrics
from hermes_db.errors import UnknownCommitError
from tests.hermes_cli.test_shared_metrics_sender_e2e import Ingest
from tests.hermes_db.postgresql.test_metrics_faults import seeded
from tests.hermes_db.postgresql.test_metrics_store import DAY

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def ingest():
    Ingest.received, Ingest.script = [], []
    server = HTTPServer(("127.0.0.1", 0), Ingest)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/telemetry"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_real_http_accepted_post_missing_receipt_retries_identical_bytes(pg_profiles, monkeypatch, ingest):
    from hermes_cli.observability.shared_metrics_sender import _post
    with pg_profiles("one"):
        store = seeded(monkeypatch)
        pools = []
        with open_metrics(store.reference) as (_conn, resource):
            pools.append(resource._transactions.engine.pool)
        def post(*args, **kwargs):
            borrowed = pools[0].checkedout()
            assert borrowed == 0
            return _post(*args, **kwargs)
        first = SharedMetricsSender(store, ingest, post=post, now=lambda: DAY + timedelta(days=1))
        def lost_receipt(*args, **kwargs):
            raise UnknownCommitError("injected receipt loss after real HTTP 202")
        monkeypatch.setattr(first, "_mark", lost_receipt)
        assert first.send_pending().deferred == 1
        assert len(Ingest.received) == 1
        later = DAY + timedelta(days=1, minutes=6)
        second = SharedMetricsSender(SharedMetricsStore(), ingest, post=post, now=lambda: later)
        assert second.send_pending().sent == 1
        assert len(Ingest.received) == 2
        assert Ingest.received[0]["raw"] == Ingest.received[1]["raw"]
        assert second.send_pending().sent == 0


def test_real_http_rate_limit_persists_backoff_after_reopen(pg_profiles, monkeypatch, ingest):
    with pg_profiles("one"):
        store = seeded(monkeypatch)
        now = DAY + timedelta(days=1)
        Ingest.script = [(429, {}, {"Retry-After": "60"})]
        first = SharedMetricsSender(store, ingest, now=lambda: now)
        assert first.send_pending().deferred == 1
        assert SharedMetricsSender(SharedMetricsStore(), ingest, now=lambda: now + timedelta(seconds=59)).send_pending().sent == 0
        assert SharedMetricsSender(SharedMetricsStore(), ingest, now=lambda: now + timedelta(seconds=60)).send_pending().sent == 1
        assert len(Ingest.received) == 2
