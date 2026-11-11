"""File effects retain actual PG transaction and competing-reference fences."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from tests.hermes_db.contracts import test_application_effect_fences as contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_replaced_spillover(pg_pair, monkeypatch):
    contracts.test_replaced_spillover_survives_committed_retirement(pg_pair, monkeypatch)


def test_last_nested_capture_pin(pg_pair):
    contracts.test_capture_retains_media_until_the_last_nested_pin(pg_pair)


def test_short_transaction_remains_active(pg_pair, monkeypatch):
    contracts.test_archive_unlink_keeps_the_actual_short_write_transaction(pg_pair, monkeypatch)


def test_reference_writer_waits_until_the_short_unlink_fence_commits(pg_store, monkeypatch):
    from sqlalchemy import text
    import hermes_cli.db_archive_files as archive_refs
    from hermes_db.domains.sessions.postgres.operations.messages import insert_rows
    from hermes_db.domains.sessions.postgres.queries import messages, sessions
    from tests.hermes_db.contracts.test_storage_health_refs import _configured
    from tests.waiting import wait_until
    _configured(monkeypatch, pg_store)
    pg_store.create_session("s", "cli")
    path = pg_store.scope.profile_home / "cache" / "spillover" / "late-reference.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unreferenced before the fence")
    active, writer_pid, future = [], [], []
    entering = Event()
    write = pg_store._transactions.write
    original = archive_refs._unlink

    @contextmanager
    def write_scope(settings, scope):
        assert scope == pg_store.scope
        with write() as conn:
            active.append(conn)
            yield conn

    def publish():
        with write() as conn:
            writer_pid.append(conn.scalar(text("SELECT pg_backend_pid()")))
            entering.set()
            sessions.lock_session(conn, pg_store.scope, "s")
            insert_rows(conn, pg_store.scope, "s", [{"role": "user", "content": str(path)}])
            messages.bump_counters(conn, pg_store.scope, "s", 1, 0)

    def fenced_unlink(*args):
        conn = active[-1]
        assert conn.in_transaction()
        owner = conn.scalar(text("SELECT pg_backend_pid()"))
        future.append(pool.submit(publish))
        assert entering.wait(15)
        wait_until(lambda: owner in conn.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid[0]}),
                   timeout=5, what="new reference waits for the live file-effect map fence")
        assert not future[0].done()
        return original(*args)

    monkeypatch.setattr(archive_refs, "_write_scope", write_scope)
    monkeypatch.setattr(archive_refs, "_unlink", fenced_unlink)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert archive_refs.cleanup_if_postgresql(pg_store.scope.profile_home, [path], cutoff=float("inf")) == 1
        future[0].result(20)
    assert not path.exists()
    assert pg_store.referenced_spillover_names() == {path.name}
    assert pg_store.get_messages("s")[0]["content"] == str(path)
