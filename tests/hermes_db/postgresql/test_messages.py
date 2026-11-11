"""Message contracts and same-lineage serialization on a real PostgreSQL service."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from contextlib import contextmanager

import pytest

from tests.hermes_db.contracts import test_messages as contracts
from tests.hermes_db.contracts import test_message_rewrites as rewrites
from tests.hermes_db.contracts import test_message_isolation as isolation

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    contracts.test_full_message_payload_and_cache_sidecars,
    contracts.test_structured_content_literal_marker_and_blob,
    contracts.test_batch_order_identity_and_row_addressed_sidecar,
    contracts.test_tool_occurrence_identity_and_resume_model_boundary,
    contracts.test_batch_failure_rolls_back_and_restores_physical_stamps,
    contracts.test_preview_keeps_first_user_even_when_inactive,
    contracts.test_compression_closed_parent_refuses_late_appends,
    contracts.test_preview_projection_of_structured_and_nul_content,
    rewrites.test_rewrite_snapshot_preserves_metadata_and_adopts_concurrent_winner,
    rewrites.test_replace_keeps_prefix_and_rewind_never_displays_removed_tail,
    rewrites.test_rewrite_cas_failure_changes_nothing,
    rewrites.test_reaction_toggle_and_seen_do_not_change_api_prefix,
    rewrites.test_result_delivery_and_completion_notes_are_durable_once,
    rewrites.test_navigation_and_resume_guard,
    rewrites.test_todo_restores_only_latest_paired_valid_result,
    rewrites.test_display_hides_model_only_and_paging_matches_count,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_message_contract_on_postgresql(pg_store, contract):
    contract(pg_store)


def test_same_schema_message_isolation(pg_store, tmp_path):
    from hermes_db.scope import DatabaseScope
    from hermes_cli.db_sessions import create_session_store
    peer = create_session_store(pg_store._transactions, DatabaseScope(tmp_path / "other", "other-store"))
    try:
        isolation.test_message_queries_mutations_and_results_are_scoped([pg_store, peer])
    finally:
        peer.close()


@pytest.mark.parametrize("operation", ["append", "watermark"])
def test_watermark_and_append_share_root_lock(pg_store, monkeypatch, operation):
    from sqlalchemy import text
    from hermes_db.domains.sessions.postgres.operations.messages import insert_rows
    from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions
    from tests.waiting import wait_until

    pg_store.create_session("s", "cli")
    inserted, waiting, blocked, release = Event(), Event(), Event(), Event()
    thread_scope, waiter_pid = local(), []
    write = pg_store._transactions.write

    @contextmanager
    def traced_write():
        with write() as conn:
            if getattr(thread_scope, "waiter", False):
                waiter_pid.append(conn.scalar(text("SELECT pg_backend_pid()")))
                waiting.set()
            yield conn

    monkeypatch.setattr(pg_store._transactions, "write", traced_write)

    def first_writer():
        with write() as conn:
            owner_pid = conn.scalar(text("SELECT pg_backend_pid()"))
            sessions.lock_session(conn, pg_store.scope, "s")
            batch = [{"role": "user", "content": "first"}]
            insert_rows(conn, pg_store.scope, "s", batch)
            repo.bump_counters(conn, pg_store.scope, "s", 1, 0)
            inserted.set()
            assert waiting.wait(15), "waiter did not acquire its own connection"
            wait_until(lambda: owner_pid in conn.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid[0]}),
                       timeout=5, what="PostgreSQL reporting the shared root lock blocker")
            blocked.set()
            assert release.wait(15), "test controller did not release writer"
            return batch[0]["_row_id"]

    def waiter():
        assert inserted.wait(15)
        thread_scope.waiter = True
        if operation == "append":
            return pg_store.append_message("s", "assistant", "second")
        return pg_store.get_active_message_watermark("s")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_writer)
        second = pool.submit(waiter)
        try:
            assert blocked.wait(15), "waiter never blocked on the original writer"
        finally:
            release.set()
        first_id, observed = first.result(15), second.result(15)
    if operation == "append":
        assert observed > first_id
        assert pg_store.get_active_message_ids("s") == [first_id, observed]
    else:
        assert observed == first_id
