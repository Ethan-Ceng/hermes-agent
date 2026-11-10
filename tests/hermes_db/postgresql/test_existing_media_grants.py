"""Existing grants on fixture-owned random PG schemas, with SQLite forbidden."""

import pytest

from tests.hermes_db.contracts import test_existing_media_grants as contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_existing_spillover_grant(pg_pair):
    contracts.test_existing_spillover_grant_pins_until_last_recipient_history(pg_pair)


@pytest.mark.parametrize("changed", ["token", "recipient_store_id"])
def test_unverified_existing_grant(pg_pair, changed):
    contracts.test_unverified_existing_grant_retains_origin_file(pg_pair, changed)


def test_changed_file_owner(pg_pair):
    contracts.test_existing_grant_does_not_collect_changed_file_owner(pg_pair)


def test_existing_media_grant(pg_pair):
    contracts.test_existing_media_grant_protects_normal_release(pg_pair)
