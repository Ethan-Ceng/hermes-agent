"""Real PG writers handle retries, immutable payloads and shutdown outside transactions."""

from threading import Event
import pytest
from plugins.memory.retaindb import _WriteQueue
from plugins.plugin_storage import open_queue
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
import plugins.plugin_storage as _plugin_storage_application
from hermes_db.tables.retain_queue import pending
from sqlalchemy import select
from tests.waiting import wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


class Client:
    base_url, project = "https://local-test.example", "project"
    def __init__(self, handler):
        self.handler = handler
    def ingest_session(self, user_id, session_id, messages):
        return self.handler(user_id, session_id, messages)


def test_failure_is_persisted_and_retry_uses_same_frozen_payload_without_connection(pg_profiles):
    calls, entered, release, completed = [], Event(), Event(), Event()
    with pg_profiles("one") as home:
        def ingest(user_id, session_id, messages):
            calls.append(messages)
            if len(calls) == 1:
                entered.set()
                assert release.wait(20)
                raise RuntimeError("password=not-a-real-secret")
            completed.set()
            return {"status": "ok"}
        queue = _WriteQueue(Client(ingest), home / "retaindb_queue.db", profile_home=home)
        try:
            source = [{"content": "original\x00🙂", "false": False}]
            queue.enqueue("user", "session", source)
            assert entered.wait(15)
            source[0]["content"] = "mutated after commit"
            with open_queue(queue.reference) as conn:
                request_id = conn.scalar(select(pending.c.request_id).where(operations.scope(queue.reference)))
            release.set()
            wait_until(lambda: _plugin_storage_application.retain_inspect(queue.reference, request_id)["status"] == "pending", what="failed RetainDB row retained with retry")
            row = _plugin_storage_application.retain_inspect(queue.reference, request_id)
            assert "not-a-real-secret" not in row["last_error"]
            assert completed.wait(15)
            assert calls == [[{"content": "original\x00🙂", "false": False}]] * 2
        finally:
            release.set()
            queue.shutdown()
        assert _plugin_storage_application.retain_inspect(queue.reference, request_id)["status"] == "acknowledged"
        queue.enqueue("user", "ignored after shutdown", [])
        assert _plugin_storage_application.retain_counts(queue.reference)["acknowledged"] == 1


def test_two_real_writers_claim_distinct_rows_while_clients_wait(pg_profiles):
    entered = [Event(), Event()]
    release = Event()
    calls = []
    with pg_profiles("one") as home:
        def ingest(user_id, session_id, messages):
            index = messages[0]["index"]
            calls.append(index)
            entered[index].set()
            assert release.wait(20)
            return {"status": "ok"}
        first = _WriteQueue(Client(ingest), home / "retaindb_queue.db", profile_home=home)
        second = None
        try:
            first.enqueue("user", "session", [{"index": 0}])
            assert entered[0].wait(15)
            first.enqueue("user", "session", [{"index": 1}])
            second = _WriteQueue(Client(ingest), home / "retaindb_queue.db", profile_home=home)
            assert entered[1].wait(15)
            with open_queue(first.reference) as conn:
                pool = conn.engine.pool
            borrowed = pool.checkedout()
            assert borrowed == 0
        finally:
            release.set()
            first.shutdown()
            if second is not None:
                second.shutdown()
        assert sorted(calls) == [0, 1]
        assert _plugin_storage_application.retain_counts(first.reference)["acknowledged"] == 2


def test_actual_ack_commit_with_missing_confirmation_does_not_resend(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    calls = []
    original = operations.acknowledge
    def lost_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise UnknownCommitError("injected post-COMMIT confirmation loss")
    monkeypatch.setattr(operations, "acknowledge", lost_ack)
    with pg_profiles("one") as home:
        queue = _WriteQueue(Client(lambda *args: calls.append(args)), home / "retaindb_queue.db", profile_home=home)
        try:
            queue.enqueue("user", "session", [{"content": "payload\x00🙂"}])
            wait_until(lambda: _plugin_storage_application.retain_counts(queue.reference)["acknowledged"] == 1, what="RetainDB committed receipt despite confirmation loss")
        finally:
            queue.shutdown()
        assert len(calls) == 1


def test_changed_remote_project_never_receives_original_pending_data(pg_profiles, caplog):
    with pg_profiles("one") as home:
        bootstrap = _WriteQueue(Client(lambda *args: None), home / "retaindb_queue.db", profile_home=home)
        bootstrap.shutdown()
        original = bootstrap.reference
        _plugin_storage_application.retain_enqueue(original, operations.prepare(original, "old-target", "user", "session", [{"content": "original project"}]))
        changed_calls = []
        changed_client = Client(lambda *args: changed_calls.append(args))
        changed_client.project = "another-project"
        changed = _WriteQueue(changed_client, home / "retaindb_queue.db", profile_home=home)
        try:
            changed.enqueue("user", "session", [{"content": "new project"}])
        finally:
            changed.shutdown()
        assert [call[2] for call in changed_calls] == [[{"content": "new project"}]]
        assert _plugin_storage_application.retain_inspect(original, "old-target")["status"] == "pending"
        assert _plugin_storage_application.retain_counts(changed.reference)["other_destination"] == 1
        assert "another endpoint/project" in caplog.text
        restored_calls, delivered = [], Event()
        def restored_ingest(*args):
            restored_calls.append(args)
            delivered.set()
        restored = _WriteQueue(Client(restored_ingest), home / "retaindb_queue.db", profile_home=home)
        try:
            assert delivered.wait(15)
        finally:
            restored.shutdown()
        assert [call[2] for call in restored_calls] == [[{"content": "original project"}]]
        assert _plugin_storage_application.retain_inspect(original, "old-target")["status"] == "acknowledged"


def test_enqueue_unknown_commit_reports_request_and_committed_work_still_delivers(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    delivered, calls = Event(), []
    original = operations.enqueue
    def lost_confirmation(*args, **kwargs):
        original(*args, **kwargs)
        raise UnknownCommitError("injected confirmation loss after actual enqueue COMMIT")
    monkeypatch.setattr(operations, "enqueue", lost_confirmation)
    with pg_profiles("one") as home:
        def ingest(*args):
            calls.append(args)
            delivered.set()
        queue = _WriteQueue(Client(ingest), home / "retaindb_queue.db", profile_home=home)
        try:
            with pytest.raises(UnknownCommitError) as outcome:
                queue.enqueue("user", "session", [{"content": "stored before wake"}])
            assert outcome.value.request_id
            assert delivered.wait(15)
        finally:
            queue.shutdown()
        receipt = _plugin_storage_application.retain_inspect(queue.reference, outcome.value.request_id)
        assert receipt["status"] == "acknowledged" and len(calls) == 1
