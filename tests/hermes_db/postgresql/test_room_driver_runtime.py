"""The production threaded driver schedules with PG persistence and a stub external session RPC."""

import pytest

from gateway import hosted_rooms as rooms
from tests.tui_gateway import test_hosted_room_driver_runtime as contracts

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CONTRACTS = [
    contracts.test_queued_task_routes_profile_and_credentials_without_overrides,
    contracts.test_worker_settles_without_any_client_transport,
    contracts.test_transport_resolver_selects_member_transport_without_forking_state,
    contracts.test_completion_wins_a_race_with_unacknowledged_stop,
    contracts.test_restart_harvests_completion_before_retrying_durable_stop,
]


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda function: function.__name__.removeprefix("test_"))
def test_real_pg_driver_runtime_contract(pg_profiles, contract):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        rooms.create_room(location, room_id="room-1", name="Release room", members=[{"profile": "ops", "handle": "ops"}], authority_gateway_id="gateway-a")
        contract(location)


def test_real_pg_runtime_deadline_releases_capacity_for_other_room(pg_profiles, monkeypatch):
    from tests.tui_gateway.test_hosted_room_worker_capacity import assert_deadline_releases_worker_capacity
    with pg_profiles("one"):
        assert_deadline_releases_worker_capacity(rooms.default_db_path(), monkeypatch)
