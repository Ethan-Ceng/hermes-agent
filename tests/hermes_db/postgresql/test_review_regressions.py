"""Review data-preservation regressions on actual PostgreSQL transactions."""

import pytest

from tests.hermes_db.contracts import test_review_data_safety as safety

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize('change', ['messages', 'prompt'])
def test_move_recipient_proof(pg_pair, change):
    safety.test_move_never_retires_source_after_recipient_snapshot_changes(pg_pair, change)


@pytest.mark.parametrize('contract', [
    safety.test_adoption_keeps_donor_after_recipient_same_length_rewrite,
    safety.test_adoption_of_missing_donor_returns_a_business_result,
    safety.test_move_allows_recipient_append_without_losing_imported_prefix,
], ids=lambda function: function.__name__)
def test_move_and_adoption_boundaries(pg_pair, contract):
    contract(pg_pair)


@pytest.mark.parametrize('in_place', [True, False])
def test_prepared_compression_append_fence(pg_pair, in_place):
    safety.test_prepared_compression_refuses_late_public_append(pg_pair, in_place)
