"""The existing driver behavior contracts run on the selected, real PG room store."""

import pytest

from gateway import hosted_rooms as rooms
from tests.gateway import test_hosted_room_driver as contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

LEASE_CONTRACTS = [
    contracts.test_two_contenders_have_one_winner,
    contracts.test_expiry_allows_reclaim_and_fences_stale_renew_and_release,
    contracts.test_nonexistent_and_disbanded_rooms_cannot_lease_or_admit,
    contracts.test_same_process_acquire_and_release_are_idempotent,
    contracts.test_renew_extends_only_the_current_lease_generation,
    contracts.test_authority_transfer_fences_lease_and_late_settlement,
    contracts.test_room_disband_fences_active_lease_operations,
    contracts.test_task_admission_is_idempotent_and_identity_conflicts_fail,
    contracts.test_concurrent_task_start_has_one_winner,
    contracts.test_stale_lease_cannot_start_or_commit_task,
    contracts.test_cancellation_fences_late_success,
    contracts.test_release_fails_closed_while_its_task_is_running,
    contracts.test_restart_recovery_never_requeues_indeterminate_work,
    contracts.test_recovery_is_required_before_starting_later_work,
    contracts.test_current_lease_can_commit_verified_indeterminate_receipt,
    contracts.test_current_lease_can_commit_verified_indeterminate_cancellation,
    contracts.test_indeterminate_retry_is_explicit_and_advances_execution_generation,
    contracts.test_indeterminate_task_can_be_deferred_retried_and_cancelled,
    contracts.test_proven_not_admitted_attempt_returns_to_queue_under_exact_fence,
    contracts.test_not_admitted_requeue_rejects_stale_lease_and_task_generation,
    contracts.test_tasks_follow_source_event_order_not_admission_time,
    contracts.test_optional_target_member_id_is_durable_and_digest_bound,
    contracts.test_invalid_lease_clock_ttl_and_settlement_schema_are_rejected,
    contracts.test_renewal_never_shortens_an_active_lease,
]


@pytest.mark.parametrize("contract", LEASE_CONTRACTS, ids=lambda function: function.__name__.removeprefix("test_"))
def test_driver_lease_contract_on_postgresql(pg_profiles, contract):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        rooms.create_room(location, room_id="room-1", name="Release room", members=[{"profile": "ops", "handle": "ops"}],
                          authority_gateway_id="gateway-a", now=90)
        contract(location)
