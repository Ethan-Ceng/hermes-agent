"""Upstream room task summaries and change notifications stay on the selected PostgreSQL store."""
import pytest

from gateway import hosted_room_driver as driver, hosted_rooms as rooms
from tests.gateway.test_hosted_room_driver import FakeClock, _admit, _identity

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def create(location, room_id="room-1"):
    rooms.create_room(location, room_id=room_id, name="Room", members=[{"profile": "ops", "handle": "ops"}],
                      authority_gateway_id="gateway-a", now=90)


def test_postgresql_task_summary_counts_and_filters_without_sqlite(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        create(location)
        _admit(location, _identity(), FakeClock())
        counts, tasks = driver.room_task_summary(location, room_id="room-1", statuses=("queued",))
        assert counts == {"queued": 1}
        assert [(task["identity"].task_id, task["status"]) for task in tasks] == [("task-1", "queued")]
        assert driver.room_task_summary(location, room_id="room-1", statuses=("running",)) == ({"queued": 1}, [])


def test_postgresql_group_changes_track_the_captured_store_and_task_state(pg_profiles, monkeypatch):
    from tui_gateway import server, hosted_room_service
    monkeypatch.setattr(server, "_served_profile_homes", set())
    monkeypatch.setattr(server, "_room_store_sig_cache", {})
    monkeypatch.setattr(hosted_room_service, "live_room_services", list)
    with pg_profiles("one") as home:
        monkeypatch.setattr(server, "_hermes_home", str(home))
        location = rooms.default_db_path()
        create(location)
        before = server._groups_sig()
        assert set(before) == {"room-1"}
        assert server._groups_sig() == before
        _admit(location, _identity(), FakeClock())
        after = server._groups_sig()
        assert after["room-1"] != before["room-1"]
    with pg_profiles("two") as home:
        monkeypatch.setattr(server, "_hermes_home", str(home))
        create(rooms.default_db_path(), "room-2")
        assert set(server._groups_sig()) == {"room-2"}
