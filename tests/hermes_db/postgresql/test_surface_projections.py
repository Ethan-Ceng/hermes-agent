"""Actual PostgreSQL startup and live viewer projections."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_webhook_recovery_retains_nul_payloads(pg_pair):
    from tests.hermes_db.contracts.test_recovery_payloads import test_webhook_recovery_preserves_nul_and_automation_presence

    test_webhook_recovery_preserves_nul_and_automation_presence(pg_pair)


def test_live_viewer_policy_target_on_postgresql(pg_store, pg_runtime):
    from tests.hermes_db.contracts.test_viewer_storage import test_viewer_close_compare_delete_and_live_facts_are_backend_scoped

    test_viewer_close_compare_delete_and_live_facts_are_backend_scoped(pg_store, pg_runtime)


def test_webhook_recovery_crosses_a_full_unrelated_batch(pg_pair):
    from tests.hermes_db.contracts.test_recovery_payloads import test_webhook_recovery_scans_past_a_full_unrelated_batch

    test_webhook_recovery_scans_past_a_full_unrelated_batch(pg_pair)


@pytest.mark.parametrize('operation', ['key_scan', 'listing', 'deletion'])
def test_model_options_do_not_break_session_projections(pg_store, operation):
    from tests.hermes_db.contracts.test_model_config_queries import test_nul_model_option_does_not_break_session_queries

    test_nul_model_option_does_not_break_session_queries(pg_store, operation)


def test_model_marker_updates_on_postgresql(pg_store):
    from tests.hermes_db.contracts.test_model_config_queries import test_model_marker_updates_keep_raw_options_and_listing_semantics

    test_model_marker_updates_keep_raw_options_and_listing_semantics(pg_store)


def test_admitted_nul_preview_on_postgresql(pg_store):
    from tests.hermes_db.contracts.test_display_query_metadata import test_admitted_nul_preview_keeps_display_reads_and_owner_lookup

    test_admitted_nul_preview_keeps_display_reads_and_owner_lookup(pg_store)
