"""Real PostgreSQL compression/lease/receipt and barrier-driven concurrency checks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from tests.hermes_db.contracts import test_compression_archive as archive
from tests.hermes_db.contracts import test_compression_atomicity as atomicity
from tests.hermes_db.contracts import test_compression_leases as leases
from tests.hermes_db.contracts import test_compression_metadata as metadata
from tests.hermes_db.contracts import test_compression_publish as publish
from tests.hermes_db.contracts import test_worker_compression as workers

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    leases.test_turn_lease_follows_compression_but_excludes_explicit_forks,
    leases.test_turn_wait_calls_owner_callbacks_between_transactions,
    leases.test_turn_write_rejects_displaced_holder,
    archive.test_compaction_keeps_late_tail_uid_and_every_payload_column,
    archive.test_named_coverage_preserves_unheld_gaps_below_watermark,
    archive.test_compaction_does_not_clone_an_already_carried_tail_occurrence,
    archive.test_compaction_refuses_lost_holder_and_rewritten_held_rows,
    publish.test_publish_keeps_prompt_tools_route_pin_and_late_tail,
    publish.test_publish_displaced_owner_or_deliberate_boundary_cannot_create_child,
    publish.test_publish_allows_stale_automatic_close_and_watermark_ceiling,
    metadata.test_compression_cooldown_merge_restore_and_numeric_state,
    metadata.test_host_explicit_reopen_excludes_automatic_and_reset_boundaries,
    atomicity.test_rewritten_carried_tail_is_compacted_history_and_not_cloned,
    atomicity.test_unaddressed_held_snapshot_rejects_rewritten_active_uid,
]
CLOCK_CONTRACTS = [
    leases.test_expired_unclaimed_lease_can_renew_but_taken_lease_cannot,
    publish.test_publish_refreshes_expired_unclaimed_lease_inside_commit,
    metadata.test_compression_orphan_recovery_retires_expired_lock_and_never_live_child,
    metadata.test_only_old_unserved_compression_children_are_finalized,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_compression_on_postgresql(pg_store, contract):
    contract(pg_store)


@pytest.mark.parametrize("contract", CLOCK_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_expiry_compression_on_postgresql(pg_store, contract, monkeypatch):
    contract(pg_store, monkeypatch)


@pytest.mark.parametrize("contract", [workers.test_worker_rotation_lost_ack_replays_once_and_preserves_fifo,
    workers.test_worker_compression_guards_and_lineage_reads_are_owned], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_worker_compression_on_postgresql(pg_store, pg_runtime, tmp_path, contract):
    contract(pg_store, pg_runtime, tmp_path)


def test_scope_and_parent_backfill_on_postgresql(pg_pair):
    leases.test_core_never_infers_remote_holder_death_from_local_pid(pg_pair)
    atomicity.test_core_late_parent_backfill_keeps_lease_and_refuses_two_live_holders(pg_pair)


def test_archive_rollback_on_postgresql(pg_pair, monkeypatch):
    atomicity.test_core_archive_failure_rolls_back_rows_config_counters_and_physical_stamps(pg_pair, monkeypatch)


def test_worker_rotation_survives_reopen_on_postgresql(pg_pair, tmp_path):
    atomicity.test_core_worker_publication_origin_retry_and_scope_survive_new_handle(pg_pair, tmp_path)


def test_local_route_publication_on_postgresql(pg_pair):
    atomicity.test_core_local_route_and_receipt_advance_atomically_with_child(pg_pair)


def test_expired_lease_renewal_and_takeover_are_serialized(pg_store):
    pg_store.create_session("s", "test")
    assert pg_store.try_acquire_compression_lock("s", "old", ttl_seconds=-1)
    gate = Barrier(2)

    def renew():
        gate.wait(15)
        return pg_store.refresh_compression_lock("s", "old")

    def acquire():
        gate.wait(15)
        return pg_store.try_acquire_compression_lock("s", "new")

    with ThreadPoolExecutor(max_workers=2) as pool:
        renewed, acquired = pool.submit(renew), pool.submit(acquire)
        assert renewed.result(20) != acquired.result(20)


def test_competing_publications_do_not_fork_parent(pg_store):
    pg_store.create_session("p", "test")
    assert pg_store.try_acquire_compression_lock("p", "owner")
    gate = Barrier(2)

    def commit(child):
        gate.wait(15)
        try:
            pg_store.publish_compression_child(parent_session_id="p", child_session_id=child, source="test",
                messages=[{"role": "user", "content": "summary"}], compression_lock_holder="owner")
            return True
        except RuntimeError as error:
            if "parent already ended" not in str(error):
                raise
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(commit, child) for child in ("c1", "c2")]
        assert sorted(future.result(20) for future in futures) == [False, True]
    assert len(pg_store.get_compression_chain("p")) == 2
    assert sum(pg_store.get_session(child) is not None for child in ("c1", "c2")) == 1


def test_summary_wait_keeps_connection_free_and_concurrent_tail_survives(pg_store):
    pg_store.create_session("s", "test")
    pg_store.append_message("s", "user", "before")
    captured, appended = Event(), Event()

    def compress():
        mark = pg_store.get_active_message_watermark("s")
        assert pg_store.try_acquire_compression_lock("s", "owner")
        captured.set()
        assert appended.wait(15)
        return pg_store.archive_and_compact("s", [{"role": "user", "content": "summary"}],
            watermark=mark, lock_holder="owner")

    def append_tail():
        assert captured.wait(15)
        pg_store.append_message("s", "assistant", "late\x00reply", api_content="late\x00wire")
        appended.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        summary, tail = pool.submit(compress), pool.submit(append_tail)
        tail.result(20)
        assert summary.result(20) == 2
    assert [row["content"] for row in pg_store.get_messages("s")] == ["summary", "late\x00reply"]
