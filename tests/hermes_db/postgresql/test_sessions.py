"""Run shared session contracts on a real, explicitly configured PG service."""

import pytest

from tests.hermes_db.contracts import test_sessions as session_contracts
from tests.hermes_db.contracts import test_prompts_usage as usage_contracts
from tests.hermes_db.contracts import test_session_queries as query_contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    session_contracts.test_creation_is_keep_existing_and_placeholder_source_is_replaced,
    session_contracts.test_end_is_first_writer_wins_and_reopen_allows_a_new_end,
    session_contracts.test_compression_child_inherits_metadata_but_branch_does_not_inherit_routing,
    session_contracts.test_lineage_visibility_flags_do_not_cross_explicit_branches,
    session_contracts.test_title_provenance_uniqueness_and_canonical_identity,
    session_contracts.test_cwd_generation_refuses_stale_background_enrichment,
    session_contracts.test_model_patch_preserves_markers_and_frozen_snapshot,
    session_contracts.test_topic_modes_bindings_and_last_binding_disable,
    session_contracts.test_profile_inheritance_does_not_cross_agent_key_namespaces,
    session_contracts.test_surface_stamping_reaches_compression_ancestors,
    session_contracts.test_title_can_transfer_forward_in_compression_but_not_backwards,
    usage_contracts.test_prompt_and_tool_pin_are_exact_and_independent_of_route_updates,
    usage_contracts.test_usage_delta_absolute_and_first_accounted_route,
    usage_contracts.test_auxiliary_usage_does_not_inherit_main_route_or_overwrite_summary,
    usage_contracts.test_queued_usage_is_flushed_before_authoritative_reads,
    usage_contracts.test_unknown_nullable_totals_are_not_replaced_with_invented_zeroes,
    query_contracts.test_list_count_source_scope_and_hidden_archive_recovery,
    query_contracts.test_compression_projection_keeps_root_ordering_and_tip_identity,
    query_contracts.test_literal_prefixes_workspace_filters_and_pinned_backfill,
    query_contracts.test_list_search_normalization_and_model_key_scan,
    query_contracts.test_origin_lookup_never_selects_another_sender,
    query_contracts.test_late_parent_fill_joins_an_empty_placeholder_to_its_compression_lineage,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_shared_contract_on_postgresql(pg_store, contract):
    contract(pg_store)
