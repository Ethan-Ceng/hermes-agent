"""Real PostgreSQL retirement, prepared mutation and rewrite concurrency contracts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from hermes_state_errors import PruneRowStaleError
from hermes_state_runtime import RuntimeStoreError
from tests.hermes_db.contracts import test_gateway_rekey as rekey
from tests.hermes_db.contracts import test_mutation_receipts as mutations
from tests.hermes_db.contracts import test_mutation_transcript as transcript
from tests.hermes_db.contracts import test_prepared_mutations as prepared
from tests.hermes_db.contracts import test_portability as portability
from tests.hermes_db.contracts import test_prune_rewrites as prune
from tests.hermes_db.contracts import test_retired_files as files
from tests.hermes_db.contracts import test_retirement_guards as guards
from tests.hermes_db.contracts import test_retirement_housekeeping as housekeeping
from tests.hermes_db.contracts import test_retirement_rewrites as retirement
from tests.hermes_db.contracts import test_terminal_retries as terminal
from tests.hermes_db.contracts import test_session_controls as controls

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

STORE_CONTRACTS = [guards.test_export_bound_counts_archived_rows_as_well_as_active_context,
    guards.test_native_delete_target_probe_includes_delegates_but_not_other_conversations,
    retirement.test_native_delete_retires_id_and_orphans_independent_conversations,
    retirement.test_chain_delete_skips_whole_selected_conversation_when_a_segment_is_leased,
    retirement.test_verified_delete_refuses_new_display_rows_or_new_delegate_targets,
    retirement.test_physical_parent_delete_keeps_orphaned_conversations_independent,
    prune.test_prune_keeps_row_slot_and_archives_only_changed_body,
    prune.test_prune_prevalidates_every_row_before_writing_or_stamping,
    prune.test_rewind_user_turn_uses_public_projection_and_rejects_changed_warm_history,
    housekeeping.test_delete_empty_is_atomic_and_never_discards_a_leased_first_turn,
    portability.test_current_export_roundtrip_preserves_archived_rows_uid_and_prompt,
    portability.test_import_validates_whole_batch_and_refuses_retired_ids_without_partial_rows,
    portability.test_import_parent_graph_detaches_cycle_and_preserves_independent_fork_root,
    portability.test_foreign_snapshot_import_is_idempotent_and_scaffold_workspace_reads_are_scoped,
    controls.test_prompt_refresh_orders_profile_and_session_requests_without_rewriting_prompt]
RUNTIME_CONTRACTS = [retirement.test_delete_refuses_live_ledger_then_keeps_only_terminal_exact_replay,
    retirement.test_delete_preserves_unknown_execution_for_explicit_resolution,
    mutations.test_metadata_mutation_receipt_replays_before_revision_and_rejects_different_request,
    mutations.test_delete_mutation_refuses_live_lease_and_replays_after_row_disappears,
    mutations.test_delete_owner_closure_stops_at_foreign_principal_even_if_later_labels_match,
    prepared.test_prepared_model_pick_keeps_prompt_tools_and_transcript_exact,
    prepared.test_prepared_policy_staleness_rolls_back_generation_and_workspace,
    transcript.test_branch_boundary_keeps_tool_answers_and_forks_policy_and_root,
    transcript.test_reset_allows_queued_follower_and_replays_without_another_child,
    transcript.test_rewind_reports_typed_ask_and_exact_receipt_after_later_append,
    transcript.test_branch_refuses_archived_boundary_without_publishing_child,
    transcript.test_prepare_commit_detects_changed_physical_target_revision,
    housekeeping.test_discard_unadmitted_allows_seed_retry_but_terminal_receipts_require_fence,
    terminal.test_private_terminal_retry_requires_original_identity_digest_and_epoch,
    terminal.test_private_terminal_worker_proof_cannot_read_erased_transcript_receipt,
    controls.test_chat_pick_receipt_fences_revision_and_replays_after_mount_changes,
    controls.test_canonical_import_receipt_exists_without_preexisting_session_and_replays_exactly,
    portability.test_current_cron_admissions_keep_exact_job_identity]
PAIR_CONTRACTS = [guards.test_core_delete_probe_is_scoped_even_with_same_parent_marker,
    retirement.test_core_delete_same_id_cannot_remove_other_store_rows_or_routes,
    housekeeping.test_core_empty_sweep_keeps_closed_ancestor_while_descendant_holds_root_lease,
    files.test_core_spillover_cleanup_keeps_shared_branch_pointer_until_last_owner,
    files.test_core_retired_media_keeps_live_input_then_releases_under_own_profile]


@pytest.mark.parametrize("contract", STORE_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_store_retirement_on_postgresql(pg_store, contract):
    contract(pg_store)


@pytest.mark.parametrize("contract", RUNTIME_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_runtime_retirement_on_postgresql(pg_store, pg_runtime, contract):
    contract(pg_store, pg_runtime)


@pytest.mark.parametrize("in_place", [True, False])
def test_prepared_compression_on_postgresql(pg_store, pg_runtime, in_place):
    transcript.test_prepared_compression_changes_target_once_and_keeps_archived_history(pg_store, pg_runtime, in_place)


@pytest.mark.parametrize("contract", PAIR_CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_scoped_retirement_on_postgresql(pg_pair, contract):
    contract(pg_pair)


def test_empty_sweep_expiry_on_postgresql(pg_store, pg_runtime, monkeypatch):
    housekeeping.test_empty_sweep_skips_pending_work_and_expires_only_non_derived_fences(pg_store, pg_runtime, monkeypatch)


def test_never_active_sweep_on_postgresql(pg_store, monkeypatch):
    housekeeping.test_never_active_sweep_keeps_leased_candidates_and_counts_only_removed_routes(pg_store, monkeypatch)


@pytest.mark.parametrize("contract", [housekeeping.test_core_derived_generation_walk_keeps_passed_expiring_fences,
    rekey.test_core_profile_rekey_retains_permanent_namespace_retirement_fences,
    mutations.test_core_mutation_receipt_failure_rolls_back_title_and_revision,
    retirement.test_core_retirement_failure_rolls_back_fences_routes_and_callbacks], ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_retirement_faults_and_scope_on_postgresql(pg_pair, monkeypatch, contract):
    contract(pg_pair, monkeypatch)


def test_snapshot_paths_on_postgresql(pg_pair, tmp_path):
    retirement.test_core_snapshot_cleanup_is_exact_and_cannot_escape_configured_directory(pg_pair, tmp_path)


def _race(*actions):
    gate = Barrier(len(actions))

    def invoke(action):
        gate.wait(15)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(invoke, action) for action in actions]
        return [future.result(30) for future in futures]


def test_concurrent_exact_branch_request_publishes_one_child(pg_store, pg_runtime):
    sid, _ = prepared.local_setup(pg_store)
    pg_store.append_message(sid, "user", "held")
    epoch = pg_runtime.begin_epoch(instance_id="owner")
    args = transcript._args(pg_store, epoch, sid, "branch", {})
    first, second = _race(*(lambda: pg_runtime.mutate_session(**args) for _ in range(2)))
    assert first == second
    assert pg_store.get_session(first["branched_session_id"])["message_count"] == 1


def test_admission_delete_interleaving_never_resurrects_target(pg_store, pg_runtime):
    pg_store.create_session("s", "cli")
    epoch = pg_runtime.begin_epoch(instance_id="owner")

    def attempt(action):
        try:
            action()
            return "committed"
        except RuntimeStoreError as error:
            return error.reason

    deleted, admitted = _race(lambda: attempt(lambda: pg_store.delete_session("s")),
        lambda: attempt(lambda: pg_runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={})))
    assert (deleted, admitted) in (("committed", "not_found"), ("session_busy", "committed"))
    assert (pg_store.get_session("s") is None) == (deleted == "committed")


def test_concurrent_prune_cas_has_one_winner_and_one_archived_twin(pg_store):
    pg_store.create_session("s", "cli")
    held = [{"role": "assistant", "content": "original"}]
    pg_store.append_messages_batch("s", held)

    def rewrite(value):
        try:
            pg_store.rewrite_pruned_rows("s", [(held[0], {**held[0], "content": value})])
            return "committed"
        except PruneRowStaleError:
            return "stale"

    assert sorted(_race(lambda: rewrite("first"), lambda: rewrite("second"))) == ["committed", "stale"]
    assert len(pg_store.get_messages("s", include_inactive=True)) == 2
