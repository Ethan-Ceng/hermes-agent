"""New-process RetainDB queue replay with no SQLite and no external service calls."""

import sqlite3
import sys
import threading

attempts, failures = [], []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite rejected in actual RetainDB PG process")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)
threading.excepthook = lambda args: failures.append(args.exc_value)
from hermes_db.factory import acquire_profile_domain
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from plugins.memory.retaindb import _WriteQueue
from hermes_constants import get_hermes_home

with acquire_profile_domain("retain_queue") as resource:
    pool = resource._transactions.engine.pool
role = sys.argv[1]
expected = 205 if role == "backlog" else 1
done, received = threading.Event(), []


class Client:
    base_url, project = "https://local-test.example", "project"
    def ingest_session(self, user_id, session_id, messages):
        borrowed = pool.checkedout()
        assert borrowed == 0
        assert user_id == "user" and session_id == "session"
        received.append(messages)
        if len(received) == expected:
            done.set()
        return {"status": "ok"}


queue = _WriteQueue(Client(), get_hermes_home() / "retaindb_queue.db")
try:
    assert done.wait(45)
finally:
    queue.shutdown()
assert not queue._thread.is_alive()
assert not attempts and not failures
if role == "backlog":
    assert sorted(messages[0]["index"] for messages in received) == list(range(205))
else:
    assert received == [[{"content": "payload\x00🙂"}]]
assert operations.counts(queue.reference)["pending"] == 0
print("PG_RETAIN_RESTART_REPLAY_OK")
