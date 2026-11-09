"""Real new-interpreter replay closes remote success/receipt loss and >200 backlog."""

from pathlib import Path
import subprocess
import sys
import pytest
from sqlalchemy import select, update
from hermes_db.domains.plugin_storage.retain.api import open_queue
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from hermes_db.tables.retain_queue import pending
from plugins.memory.retaindb import _WriteQueue
from tests.hermes_db.postgresql.test_retain_queue_worker import Client
from tests.waiting import wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def replay(home, role):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    env = child_env()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
    script = Path(__file__).with_name("scenarios") / "retain_recovery.py"
    result = subprocess.run([sys.executable, str(script), role], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "PG_RETAIN_RESTART_REPLAY_OK" in result.stdout


def test_remote_success_without_local_ack_replays_identical_data_after_restart(pg_profiles, monkeypatch):
    calls = []
    with pg_profiles("one") as home:
        def no_ack(*args, **kwargs):
            raise UnknownCommitError("injected missing receipt after remote accepted")
        monkeypatch.setattr(operations, "acknowledge", no_ack)
        queue = _WriteQueue(Client(lambda *args: calls.append(args)), home / "retaindb_queue.db", profile_home=home)
        try:
            queue.enqueue("user", "session", [{"content": "payload\x00🙂"}])
            wait_until(lambda: len(calls) == 1, what="RetainDB remote accepted request")
        finally:
            queue.shutdown()
        assert operations.counts(queue.reference)["pending"] == 1
        with open_queue(queue.reference, write=True) as conn:
            row = conn.execute(select(pending).where(operations.scope(queue.reference))).mappings().one()
            request_id = row["request_id"]
            # Model elapsed crash-lease time without sleeping for the production TTL.
            conn.execute(update(pending).where(operations.key(queue.reference, request_id)).values(lease_until=0))
        replay(home, "replay")
        assert operations.inspect(queue.reference, request_id)["status"] == "acknowledged"


def test_restart_drains_all_205_persisted_rows_not_only_first_200(pg_profiles):
    with pg_profiles("one") as home:
        bootstrap = _WriteQueue(Client(lambda *args: None), home / "retaindb_queue.db", profile_home=home)
        bootstrap.shutdown()
        reference = bootstrap.reference
        for index in range(205):
            operations.enqueue(reference, operations.prepare(reference, f"backlog-{index:03d}", "user", "session", [{"index": index}]))
        assert operations.counts(reference)["pending"] == 205
        replay(home, "backlog")
        assert operations.counts(reference) == dict(pending=0, other_destination=0, acknowledged=205)
