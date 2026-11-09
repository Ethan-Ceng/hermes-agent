"""Actual RetainDB provider queue must persist and send through selected PG only."""

from threading import Event
import pytest
from plugins.memory import retaindb
from hermes_db.domains.plugin_storage.retain.api import open_queue, capture_queue
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from hermes_db.tables.retain_queue import pending
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_actual_provider_sync_turn_uses_pg_and_waits_without_borrowing_connection(pg_profiles, monkeypatch):
    started, release = Event(), Event()
    calls = []
    class Client:
        def __init__(self, api_key, base_url, project):
            self.base_url, self.project = base_url, project
        def ingest_session(self, user_id, session_id, messages):
            calls.append((user_id, session_id, messages))
            started.set()
            assert release.wait(20)
            return {"status": "ok"}
    monkeypatch.setattr(retaindb, "_Client", Client)
    with pg_profiles("one") as home:
        provider = retaindb.RetainDBMemoryProvider()
        try:
            provider.initialize("session", hermes_home=str(home), user_id="user")
            provider.sync_turn("零\x00🙂", "reply\x00🙂")
            assert started.wait(15)
            assert calls[0][0:2] == ("user", "session")
            assert calls[0][2][0]["content"] == "零\x00🙂"
            reference = provider._queue.reference
            with open_queue(reference) as conn:
                row = conn.execute(select(pending).where(operations.scope(reference))).mappings().one()
                request_id = row["request_id"]
                pool = conn.engine.pool
                assert row["status"] == "claimed" and row["messages_json"] is not None
            borrowed = pool.checkedout()
            assert borrowed == 0
            with pg_profiles("two") as peer_home:
                peer = capture_queue(peer_home, reference.destination_id)
                assert operations.counts(peer)["pending"] == 0
        finally:
            release.set()
            provider.shutdown()
        receipt = operations.inspect(reference, request_id)
        assert receipt["status"] == "acknowledged"
        assert receipt["user_id"] is None and receipt["session_id"] is None and receipt["messages_json"] is None


def test_provider_initialization_and_worker_bind_explicit_owner_under_another_profile(pg_profiles, monkeypatch):
    from agent.secret_scope import current_secret_scope_home, get_secret
    from hermes_cli.config import read_raw_config_readonly, atomic_config_write
    completed = Event()
    captured = {}
    class Client:
        def __init__(self, api_key, base_url, project):
            self.base_url, self.project = base_url, project
            captured.update(api_key=api_key, base_url=base_url, project=project)
        def ingest_session(self, user_id, session_id, messages):
            captured.update(worker_home=current_secret_scope_home(), worker_secret=get_secret("RETAINDB_API_KEY"))
            completed.set()
            return {"status": "ok"}
    monkeypatch.setattr(retaindb, "_Client", Client)
    with pg_profiles("one") as owner:
        config = read_raw_config_readonly()
        config["memory"] = {"retaindb": {"base_url": "https://owner.example", "project": "owner-project"}}
        atomic_config_write(owner / "config.yaml", config)
        with (owner / ".env").open("a", encoding="utf-8") as file:
            file.write("RETAINDB_API_KEY=owner-test-secret\n")
    with pg_profiles("two"):
        provider = retaindb.RetainDBMemoryProvider()
        try:
            provider.initialize("session", hermes_home=str(owner))
            reference = provider._queue.reference
            provider.sync_turn("owned content", "reply")
            assert completed.wait(15)
            assert captured == dict(api_key="owner-test-secret", base_url="https://owner.example", project="owner-project",
                worker_home=str(owner), worker_secret="owner-test-secret")
            assert reference.store_id == "one"
        finally:
            provider.shutdown()
