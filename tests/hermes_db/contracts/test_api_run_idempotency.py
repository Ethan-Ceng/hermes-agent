"""Run reservations preserve accepted identity across restart and retention expiry."""

import time

import pytest


@pytest.fixture
def run_store_factory(store):
    from hermes_state import SessionDB
    children = []

    def create():
        if isinstance(store, SessionDB):
            from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
            child = RunIdempotencyStore(str(store.db_path.parent / "runs_idempotency.db"))
        else:
            from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
            child = PostgresRunIdempotencyStore(store)
        children.append(child)
        return child

    yield create
    for child in children:
        child.close()


def test_run_reservation_reopens_exact_identity_and_scopes_conflicts(run_store_factory):
    store = run_store_factory()
    assert store.durable
    outcome, row = store.reserve("tenant", "key", "digest", "run", {"status": "running"}, owner_pid=12, owner_started=34)
    assert outcome == "created" and row["owner_pid"] == 12 and row["owner_started"] == 34
    assert store.reserve("tenant", "key", "different", "other", {"status": "queued"})[0] == "conflict"
    assert store.reserve("other", "key", "digest", "other-run", {"status": "queued"})[0] == "created"
    store.close()
    reopened = run_store_factory()
    outcome, replay = reopened.lookup("tenant", "key", "digest")
    assert outcome == "reused" and replay["run_id"] == "run" and replay["status"]["status"] == "running"
    assert not reopened.owns_run("other", "run")


def test_run_retention_keeps_unsettled_and_extends_matching_terminal_grant(run_store_factory, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000000.0)
    store = run_store_factory()
    store.reserve("tenant", "active", "active", "active-run", {"status": "running"})
    store.reserve("tenant", "done", "done", "done-run", {"status": "completed"})
    store.reserve("tenant", "room", "room", "room-run", {"status": "completed"}, retention_until=1000000 + 30 * 86400)
    monkeypatch.setattr(time, "time", lambda: 1000000.0 + 2 * 86400)
    assert store.lookup("tenant", "done", "done")[0] == "missing"
    assert store.lookup("tenant", "active", "active")[0] == "reused"
    assert store.lookup("tenant", "room", "room")[0] == "reused"
    assert store.extend_retention("tenant", "room-run", 1000000 + 60 * 86400)
    monkeypatch.setattr(time, "time", lambda: 1000000.0 + 31 * 86400)
    assert store.lookup("tenant", "room", "room")[0] == "reused"
