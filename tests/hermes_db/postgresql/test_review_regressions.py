"""Prepared compression preserves late-append conflicts on real PostgreSQL."""

import pytest

from tests.hermes_db.contracts import test_review_data_safety as safety

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize('in_place', [True, False])
def test_prepared_compression_append_fence(pg_pair, in_place):
    safety.test_prepared_compression_refuses_late_public_append(pg_pair, in_place)
